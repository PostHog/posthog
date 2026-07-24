import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./logger", () => ({
  networkLog: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("./network-log", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./network-log")>();
  return {
    ...actual,
    recordNetworkRequest: vi.fn(),
  };
});

import { createNetworkLoggingFetch } from "./network-fetch-logger";
import { recordNetworkRequest } from "./network-log";

const mockedRecord = vi.mocked(recordNetworkRequest);

function fakeResponse(
  status = 200,
  headers: Record<string, string> = { "content-length": "1834" },
): Response {
  return new Response(null, { status, headers });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("createNetworkLoggingFetch", () => {
  it("records a successful request with status, duration and bytes", async () => {
    const original = vi.fn(async () => fakeResponse());
    const wrapped = createNetworkLoggingFetch(
      original as unknown as typeof fetch,
    );

    const response = await wrapped("https://us.posthog.com/api/", {
      method: "post",
    });

    expect(response.status).toBe(200);
    expect(original).toHaveBeenCalledWith("https://us.posthog.com/api/", {
      method: "post",
    });
    expect(mockedRecord).toHaveBeenCalledWith({
      origin: "main",
      method: "POST",
      url: "https://us.posthog.com/api/",
      status: 200,
      durationMs: expect.any(Number),
      bytes: 1834,
    });
  });

  it.each([
    ["string", "https://example.com/a", "https://example.com/a", "GET"],
    ["URL", new URL("https://example.com/b"), "https://example.com/b", "GET"],
    [
      "Request",
      new Request("https://example.com/c", { method: "PUT" }),
      "https://example.com/c",
      "PUT",
    ],
  ])(
    "extracts url and method from %s input",
    async (_kind, input, url, method) => {
      const original = vi.fn(async () => fakeResponse());
      const wrapped = createNetworkLoggingFetch(
        original as unknown as typeof fetch,
      );

      await wrapped(input);

      expect(mockedRecord).toHaveBeenCalledWith(
        expect.objectContaining({ url, method }),
      );
    },
  );

  it("records null bytes when content-length is missing", async () => {
    const original = vi.fn(async () => fakeResponse(204, {}));
    const wrapped = createNetworkLoggingFetch(
      original as unknown as typeof fetch,
    );

    await wrapped("https://example.com/");

    expect(mockedRecord).toHaveBeenCalledWith(
      expect.objectContaining({ status: 204, bytes: null }),
    );
  });

  it("records and rethrows async rejections", async () => {
    const original = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    const wrapped = createNetworkLoggingFetch(
      original as unknown as typeof fetch,
    );

    await expect(wrapped("https://example.com/")).rejects.toThrow(
      "fetch failed",
    );
    expect(mockedRecord).toHaveBeenCalledWith(
      expect.objectContaining({
        status: null,
        bytes: null,
        error: "TypeError: fetch failed",
      }),
    );
  });

  it("records and rethrows synchronous throws", async () => {
    const original = vi.fn(() => {
      throw new Error("boom");
    });
    const wrapped = createNetworkLoggingFetch(
      original as unknown as typeof fetch,
    );

    await expect(wrapped("https://example.com/")).rejects.toThrow("boom");
    expect(mockedRecord).toHaveBeenCalledWith(
      expect.objectContaining({ error: "Error: boom" }),
    );
  });

  it("forwards preconnect from the original fetch", () => {
    const preconnect = vi.fn();
    const original = Object.assign(
      vi.fn(async () => fakeResponse()),
      {
        preconnect,
      },
    );
    const wrapped = createNetworkLoggingFetch(
      original as unknown as typeof fetch,
    );

    (wrapped as unknown as { preconnect: (origin: string) => void }).preconnect(
      "https://example.com",
    );

    expect(preconnect).toHaveBeenCalledWith("https://example.com");
  });
});

describe("installMainFetchLogging", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("wraps globalThis.fetch once and stays idempotent", async () => {
    const original = vi.fn(async () => fakeResponse());
    vi.stubGlobal("fetch", original);

    vi.resetModules();
    const { installMainFetchLogging } = await import("./network-fetch-logger");

    installMainFetchLogging();
    const wrappedOnce = globalThis.fetch;
    expect(wrappedOnce).not.toBe(original);

    installMainFetchLogging();
    expect(globalThis.fetch).toBe(wrappedOnce);

    await globalThis.fetch("https://example.com/");
    expect(original).toHaveBeenCalledOnce();
  });
});
