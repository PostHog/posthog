import {
  mkdtempSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { secureStoreRouter } from "@posthog/host-router/routers/secure-store.router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ElectronClaudeSubscriptionTokenStore } from "../../platform-adapters/electron-claude-subscription-token-store";
import { type SecureStoreBackend, SecureStoreService } from "./service";

const safeStorage = vi.hoisted(() => ({
  isEncryptionAvailable: vi.fn(() => true),
  getSelectedStorageBackend: vi.fn(() => "gnome_libsecret"),
  encryptString: vi.fn((value: string) => Buffer.from(`encrypted:${value}`)),
  decryptString: vi.fn((value: Buffer) => value.toString().slice(10)),
}));

vi.mock("electron", () => ({ safeStorage }));

function makeFakeBackend(initial: Record<string, string> = {}) {
  const data = new Map<string, string>(Object.entries(initial));
  const backend: SecureStoreBackend = {
    has: (key) => data.has(key),
    get: (key) => data.get(key),
    set: (key, value) => {
      data.set(key, value);
    },
    delete: (key) => {
      data.delete(key);
    },
    clear: () => {
      data.clear();
    },
  };
  return { backend, data };
}

const tokenDirectories: string[] = [];

function makeTokenStore(
  getAccountKey = async (): Promise<string | null> => "account-1",
) {
  const directory = mkdtempSync(join(tmpdir(), "claude-token-test-"));
  tokenDirectories.push(directory);
  return {
    store: new ElectronClaudeSubscriptionTokenStore(directory, getAccountKey),
    directory,
  };
}

afterEach(() => {
  for (const directory of tokenDirectories.splice(0))
    rmSync(directory, { recursive: true, force: true });
});

describe("SecureStoreService", () => {
  it("round-trips a value through encryption", () => {
    const { backend, data } = makeFakeBackend();
    const service = new SecureStoreService(backend);

    service.setItem("token", "secret-value");

    // Persisted bytes are encrypted, never plaintext.
    expect(data.get("token")).toBeDefined();
    expect(data.get("token")).not.toBe("secret-value");

    expect(service.getItem("token")).toBe("secret-value");
  });

  it("returns null for a missing key", () => {
    const { backend } = makeFakeBackend();
    const service = new SecureStoreService(backend);
    expect(service.getItem("nope")).toBeNull();
  });

  it("keeps the Claude token outside the renderer store and removes it with Clear all data", async () => {
    const { store, directory } = makeTokenStore();
    const renderer = new SecureStoreService(makeFakeBackend().backend, store);
    const caller = secureStoreRouter.createCaller({
      container: { get: <T>() => renderer as T },
    });
    await store.save("fake-token");
    await expect(store.has()).resolves.toBe(true);
    const files = readdirSync(directory);
    expect(files).toHaveLength(1);
    expect(readFileSync(join(directory, files[0])).toString()).toBe(
      "encrypted:fake-token",
    );
    if (process.platform !== "win32")
      expect(statSync(join(directory, files[0])).mode & 0o777).toBe(0o600);
    await expect(caller.getItem({ key: "token" })).resolves.toBeNull();
    await caller.clear();
    await expect(store.has()).resolves.toBe(false);
  });

  it.each(["other-user", "other-server"])(
    "separates the token from %s",
    async (otherAccount) => {
      const account = vi.fn(
        async (): Promise<string | null> => "original-account",
      );
      const { store } = makeTokenStore(account);
      await store.save("fake-token");
      account.mockResolvedValue(otherAccount);
      await expect(store.get()).resolves.toBeNull();
      await expect(store.get("original-account")).rejects.toThrow("Sign in");
      await store.save("other-token");
      await store.clear();
      account.mockResolvedValue("original-account");
      await expect(store.get()).resolves.toBe("fake-token");
      account.mockResolvedValue(null);
      await store.clearAll();
      account.mockResolvedValue("original-account");
      await expect(store.get()).resolves.toBeNull();
    },
  );

  it.each(["unavailable", "encrypt", "write", "decrypt"] as const)(
    "keeps the previous token when OS storage fails at %s",
    async (failure) => {
      const { store, directory } = makeTokenStore();
      await store.save("fake-token");
      if (failure === "unavailable") {
        safeStorage.isEncryptionAvailable.mockReturnValueOnce(false);
      } else if (failure === "encrypt") {
        safeStorage.encryptString.mockImplementationOnce(() => {
          throw new Error("encryption failed");
        });
      } else if (failure === "write") {
        renameSync(directory, `${directory}.saved`);
        writeFileSync(directory, "blocked");
      } else {
        safeStorage.decryptString.mockImplementationOnce(() => {
          throw new Error("key store locked");
        });
      }
      try {
        await expect(
          failure === "decrypt" ? store.get() : store.save("replacement-token"),
        ).rejects.toThrow();
      } finally {
        if (failure === "write") {
          rmSync(directory);
          renameSync(`${directory}.saved`, directory);
        }
      }
      await expect(store.get()).resolves.toBe("fake-token");
    },
  );

  it("can replace or remove a token that cannot be decrypted", async () => {
    const { store } = makeTokenStore();
    await store.save("fake-token");
    safeStorage.decryptString.mockImplementationOnce(() => {
      throw new Error("invalid ciphertext");
    });
    await expect(store.has()).rejects.toThrow("replace or remove");
    await store.save("replacement-token");
    await expect(store.get()).resolves.toBe("replacement-token");
    await store.clear();
    await expect(store.has()).resolves.toBe(false);
  });

  it("rejects the Linux plain text backend", async () => {
    const platform = process.platform;
    Object.defineProperty(process, "platform", { value: "linux" });
    safeStorage.getSelectedStorageBackend.mockReturnValueOnce("basic_text");
    const { store, directory } = makeTokenStore();
    try {
      await expect(store.save("fake-token")).rejects.toThrow(
        "Secure storage is not available",
      );
      expect(readdirSync(directory)).toEqual([]);
    } finally {
      Object.defineProperty(process, "platform", { value: platform });
    }
  });

  it("removes a stored item", () => {
    const { backend } = makeFakeBackend();
    const service = new SecureStoreService(backend);
    service.setItem("k", "v");
    service.removeItem("k");
    expect(service.getItem("k")).toBeNull();
  });

  it("clears all items", async () => {
    const { backend, data } = makeFakeBackend();
    const service = new SecureStoreService(backend);
    service.setItem("a", "1");
    service.setItem("b", "2");
    await service.clear();
    expect(data.size).toBe(0);
  });

  it("degrades to null on a backend read failure without throwing", () => {
    const { backend } = makeFakeBackend();
    vi.spyOn(backend, "has").mockImplementation(() => {
      throw new Error("backend down");
    });
    const service = new SecureStoreService(backend);
    expect(service.getItem("k")).toBeNull();
  });
});
