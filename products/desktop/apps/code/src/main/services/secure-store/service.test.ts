import { describe, expect, it, vi } from "vitest";
import { type SecureStoreBackend, SecureStoreService } from "./service";

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
