import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiRequestError,
  buildApiFetcher,
  requestErrorStatus,
} from "./fetcher";

describe("buildApiFetcher", () => {
  const mockFetch = vi.fn();
  const mockInput = {
    method: "get" as const,
    url: new URL("https://api.example.com/test"),
    path: "/test",
  };
  const ok = (data = {}) => ({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
  });
  const err = (status: number, body: object = { error: status }) => {
    const response = {
      ok: false,
      status,
      statusText: `Error ${status}`,
      json: () => Promise.resolve(body),
      clone: () => ({
        ...response,
        text: () => Promise.resolve(JSON.stringify(body)),
      }),
    };
    return response;
  };

  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("fetch", mockFetch);
  });

  it("makes request with a token fetched from the provider", async () => {
    const getAccessToken = vi.fn().mockResolvedValue("my-token");
    const refreshAccessToken = vi.fn().mockResolvedValue("new-token");
    mockFetch.mockResolvedValueOnce(ok());

    const fetcher = buildApiFetcher({
      getAccessToken,
      refreshAccessToken,
      appVersion: "test",
    });
    await fetcher.fetch(mockInput);

    expect(getAccessToken).toHaveBeenCalledTimes(1);
    expect(refreshAccessToken).not.toHaveBeenCalled();
    expect(mockFetch.mock.calls[0][1].headers.get("Authorization")).toBe(
      "Bearer my-token",
    );
  });

  it("retries once with a freshly fetched token on 401", async () => {
    const getAccessToken = vi.fn().mockResolvedValue("old-token");
    const refreshAccessToken = vi.fn().mockResolvedValue("new-token");
    mockFetch.mockResolvedValueOnce(err(401)).mockResolvedValueOnce(ok());

    const fetcher = buildApiFetcher({
      getAccessToken,
      refreshAccessToken,
      appVersion: "test",
    });
    const response = await fetcher.fetch(mockInput);

    expect(response.ok).toBe(true);
    expect(getAccessToken).toHaveBeenCalledTimes(1);
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(mockFetch.mock.calls[1][1].headers.get("Authorization")).toBe(
      "Bearer new-token",
    );
  });

  it("does not retry on 403 without authentication_failed body", async () => {
    const getAccessToken = vi.fn().mockResolvedValue("token");
    const refreshAccessToken = vi.fn().mockResolvedValue("new-token");
    mockFetch.mockResolvedValueOnce(err(403, { detail: "Permission denied." }));

    const fetcher = buildApiFetcher({
      getAccessToken,
      refreshAccessToken,
      appVersion: "test",
    });

    await expect(fetcher.fetch(mockInput)).rejects.toThrow("[403]");
    expect(getAccessToken).toHaveBeenCalledTimes(1);
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it("retries with a fresh token on 403 with authentication_failed body", async () => {
    const getAccessToken = vi.fn().mockResolvedValue("stale-token");
    const refreshAccessToken = vi.fn().mockResolvedValue("fresh-token");
    mockFetch
      .mockResolvedValueOnce(
        err(403, {
          type: "authentication_error",
          code: "authentication_failed",
          detail: "Invalid access token.",
        }),
      )
      .mockResolvedValueOnce(ok());

    const fetcher = buildApiFetcher({
      getAccessToken,
      refreshAccessToken,
      appVersion: "test",
    });
    const response = await fetcher.fetch(mockInput);

    expect(response.ok).toBe(true);
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    expect(mockFetch.mock.calls[1][1].headers.get("Authorization")).toBe(
      "Bearer fresh-token",
    );
  });

  it("does not retry on other 4xx errors", async () => {
    const refreshAccessToken = vi.fn().mockResolvedValue("new-token");
    mockFetch.mockResolvedValueOnce(err(400, { detail: "Bad request." }));

    const fetcher = buildApiFetcher({
      getAccessToken: vi.fn().mockResolvedValue("token"),
      refreshAccessToken,
      appVersion: "test",
    });

    await expect(fetcher.fetch(mockInput)).rejects.toThrow("[400]");
    expect(refreshAccessToken).not.toHaveBeenCalled();
  });

  it("throws when the retry still returns 401", async () => {
    const getAccessToken = vi.fn().mockResolvedValue("token-1");
    const refreshAccessToken = vi.fn().mockResolvedValue("token-2");
    mockFetch.mockResolvedValueOnce(err(401)).mockResolvedValueOnce(err(401));

    const fetcher = buildApiFetcher({
      getAccessToken,
      refreshAccessToken,
      appVersion: "test",
    });

    await expect(fetcher.fetch(mockInput)).rejects.toThrow("[401]");
  });

  it("throws when refetching a token fails during retry", async () => {
    const getAccessToken = vi.fn().mockResolvedValue("token");
    const refreshAccessToken = vi
      .fn()
      .mockRejectedValueOnce(new Error("failed"));
    mockFetch.mockResolvedValueOnce(err(401));

    const fetcher = buildApiFetcher({
      getAccessToken,
      refreshAccessToken,
      appVersion: "test",
    });

    await expect(fetcher.fetch(mockInput)).rejects.toThrow("[401]");
  });

  it("handles network errors", async () => {
    mockFetch.mockRejectedValueOnce(new Error("Network failure"));
    const fetcher = buildApiFetcher({
      getAccessToken: vi.fn().mockResolvedValue("token"),
      refreshAccessToken: vi.fn().mockResolvedValue("new-token"),
      appVersion: "test",
    });

    await expect(fetcher.fetch(mockInput)).rejects.toThrow(
      "Network request failed",
    );
  });

  it("throws an ApiRequestError with a typed status and the legacy message format", async () => {
    mockFetch.mockResolvedValueOnce(err(404, { detail: "Not found" }));
    const fetcher = buildApiFetcher({
      getAccessToken: vi.fn().mockResolvedValue("token"),
      refreshAccessToken: vi.fn().mockResolvedValue("new-token"),
      appVersion: "test",
    });

    const error = await fetcher.fetch(mockInput).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiRequestError);
    expect((error as ApiRequestError).status).toBe(404);
    // Catch sites across the codebase string-match on this exact format.
    expect((error as ApiRequestError).message).toBe(
      'Failed request: [404] {"detail":"Not found"}',
    );
  });

  it("throws an ApiRequestError when refetching a token fails during retry", async () => {
    mockFetch.mockResolvedValueOnce(err(401));
    const fetcher = buildApiFetcher({
      getAccessToken: vi.fn().mockResolvedValue("token"),
      refreshAccessToken: vi.fn().mockRejectedValueOnce(new Error("failed")),
      appVersion: "test",
    });

    const error = await fetcher.fetch(mockInput).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiRequestError);
    expect((error as ApiRequestError).status).toBe(401);
  });
});

describe("requestErrorStatus", () => {
  it("returns the status of an ApiRequestError", () => {
    expect(requestErrorStatus(new ApiRequestError(404, "{}"))).toBe(404);
  });

  it("returns undefined for plain errors and non-errors", () => {
    expect(requestErrorStatus(new Error("Failed request: [404] x"))).toBe(
      undefined,
    );
    expect(requestErrorStatus("Failed request: [404] x")).toBe(undefined);
    expect(requestErrorStatus(null)).toBe(undefined);
  });
});
