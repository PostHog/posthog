import { secureStoreRouter } from "@posthog/host-router/routers/secure-store.router";
import { describe, expect, it, vi } from "vitest";
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

  it("keeps the Claude token outside the renderer store", async () => {
    const renderer = new SecureStoreService(makeFakeBackend().backend);
    const { backend, data } = makeFakeBackend();
    const store = new ElectronClaudeSubscriptionTokenStore(backend);
    const caller = secureStoreRouter.createCaller({
      container: { get: <T>() => renderer as T },
    });
    await store.save("fake-token");
    await expect(store.has()).resolves.toBe(true);
    expect(data.get("token")).toBe(
      Buffer.from("encrypted:fake-token").toString("base64"),
    );
    await expect(caller.getItem({ key: "token" })).resolves.toBeNull();
    await caller.clear();
    await expect(store.get()).resolves.toBe("fake-token");
    await store.clear();
    await expect(store.has()).resolves.toBe(false);
  });

  it.each(["unavailable", "encrypt", "write", "decrypt"] as const)(
    "keeps the previous token when OS storage fails at %s",
    async (failure) => {
      const { backend } = makeFakeBackend();
      const store = new ElectronClaudeSubscriptionTokenStore(backend);
      await store.save("fake-token");
      if (failure === "unavailable") {
        vi.mocked(safeStorage.isEncryptionAvailable).mockReturnValueOnce(false);
      } else if (failure === "encrypt") {
        vi.mocked(safeStorage.encryptString).mockImplementationOnce(() => {
          throw new Error("encryption failed");
        });
      } else if (failure === "write") {
        vi.spyOn(backend, "set").mockImplementationOnce(() => {
          throw new Error("disk full");
        });
      } else {
        vi.mocked(safeStorage.decryptString).mockImplementationOnce(() => {
          throw new Error("key store locked");
        });
      }

      await expect(
        failure === "decrypt" ? store.get() : store.save("replacement-token"),
      ).rejects.toThrow();
      await expect(store.get()).resolves.toBe("fake-token");
    },
  );

  it("rejects the Linux plain text backend", async () => {
    const platform = process.platform;
    Object.defineProperty(process, "platform", { value: "linux" });
    vi.mocked(safeStorage.getSelectedStorageBackend).mockReturnValueOnce(
      "basic_text",
    );
    const { backend, data } = makeFakeBackend();
    try {
      const store = new ElectronClaudeSubscriptionTokenStore(backend);
      await expect(store.save("fake-token")).rejects.toThrow(
        "Secure storage is not available",
      );
      expect(data.size).toBe(0);
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

  it("clears all items", () => {
    const { backend, data } = makeFakeBackend();
    const service = new SecureStoreService(backend);
    service.setItem("a", "1");
    service.setItem("b", "2");
    service.clear();
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
