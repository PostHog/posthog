import type { ISecureStorage } from "@posthog/platform/secure-storage";
import { describe, expect, it } from "vitest";
import { EncryptionService } from "./service";

function makeSecureStorage(available: boolean): ISecureStorage {
  return {
    isAvailable: () => available,
    // Trivial reversible "cipher": prefix the bytes so we can assert framing.
    encryptString: async (text) =>
      new Uint8Array(Buffer.from(`enc:${text}`, "utf8")),
    decryptString: async (data) =>
      Buffer.from(data).toString("utf8").replace(/^enc:/, ""),
  };
}

describe("EncryptionService", () => {
  it("round-trips a value through the host cipher as base64", async () => {
    const service = new EncryptionService(makeSecureStorage(true));
    const encrypted = await service.encrypt("secret");
    expect(encrypted).not.toBeNull();
    expect(encrypted).not.toBe("secret");
    // base64 of the cipher output
    expect(encrypted).toBe(
      Buffer.from("enc:secret", "utf8").toString("base64"),
    );
    expect(await service.decrypt(encrypted as string)).toBe("secret");
  });

  it("passes through unchanged when secure storage is unavailable", async () => {
    const service = new EncryptionService(makeSecureStorage(false));
    expect(await service.encrypt("plain")).toBe("plain");
    expect(await service.decrypt("plain")).toBe("plain");
  });

  it("returns null when the cipher throws", async () => {
    const broken: ISecureStorage = {
      isAvailable: () => true,
      encryptString: async () => {
        throw new Error("cipher down");
      },
      decryptString: async () => {
        throw new Error("cipher down");
      },
    };
    const service = new EncryptionService(broken);
    expect(await service.encrypt("x")).toBeNull();
    expect(await service.decrypt("x")).toBeNull();
  });
});
