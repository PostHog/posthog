import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockFetch, mockRefreshAccessToken, mockGetState } = vi.hoisted(() => ({
  mockFetch: vi.fn(),
  mockRefreshAccessToken: vi.fn(),
  mockGetState: vi.fn(),
}));

vi.mock("expo/fetch", () => ({
  fetch: mockFetch,
}));

vi.mock("expo-constants", () => ({
  default: { expoConfig: { version: "0.0.0-test" } },
}));

vi.mock("@/features/auth", () => ({
  useAuthStore: {
    getState: mockGetState,
  },
}));

import { authedFetch } from "./api";

const url = "https://app.posthog.test/api/projects/1/tasks/";
const ok = (data: unknown = {}) =>
  new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
const err = (status: number, body: unknown = { error: status }) =>
  new Response(JSON.stringify(body), {
    status,
    statusText: `Error ${status}`,
    headers: { "Content-Type": "application/json" },
  });

function setupTokens(initial = "old-token", refreshed = "new-token") {
  let current = initial;
  mockRefreshAccessToken.mockImplementation(async () => {
    current = refreshed;
  });
  mockGetState.mockImplementation(() => ({
    oauthAccessToken: current,
    refreshAccessToken: mockRefreshAccessToken,
  }));
}

describe("authedFetch", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockRefreshAccessToken.mockReset();
    mockGetState.mockReset();
  });

  it("attaches the bearer token from the auth store", async () => {
    setupTokens("my-token");
    mockFetch.mockResolvedValueOnce(ok());

    await authedFetch(url);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockRefreshAccessToken).not.toHaveBeenCalled();
    expect(mockFetch.mock.calls[0][1].headers.Authorization).toBe(
      "Bearer my-token",
    );
  });

  it.each([
    {
      name: "401",
      failure: () => err(401),
    },
    {
      name: "403 with authentication_failed body",
      failure: () =>
        err(403, {
          type: "authentication_error",
          code: "authentication_failed",
          detail: "Invalid access token.",
        }),
    },
  ])(
    "retries once with a freshly fetched token on $name",
    async ({ failure }) => {
      setupTokens("old-token", "new-token");
      mockFetch.mockResolvedValueOnce(failure()).mockResolvedValueOnce(ok());

      const response = await authedFetch(url);

      expect(response.ok).toBe(true);
      expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(mockFetch.mock.calls[0][1].headers.Authorization).toBe(
        "Bearer old-token",
      );
      expect(mockFetch.mock.calls[1][1].headers.Authorization).toBe(
        "Bearer new-token",
      );
    },
  );

  it.each([
    {
      name: "403 without authentication_failed body",
      response: () => err(403, { detail: "Permission denied." }),
      expectedStatus: 403,
    },
    {
      name: "400 bad request",
      response: () => err(400, { detail: "Bad request." }),
      expectedStatus: 400,
    },
  ])(
    "does not retry on $name",
    async ({ response: makeResponse, expectedStatus }) => {
      setupTokens("token");
      mockFetch.mockResolvedValueOnce(makeResponse());

      const response = await authedFetch(url);

      expect(response.status).toBe(expectedStatus);
      expect(mockRefreshAccessToken).not.toHaveBeenCalled();
      expect(mockFetch).toHaveBeenCalledTimes(1);
    },
  );

  it("returns the failed response when the retry still 401s", async () => {
    setupTokens("token-1", "token-2");
    mockFetch.mockResolvedValueOnce(err(401)).mockResolvedValueOnce(err(401));

    const response = await authedFetch(url);

    expect(response.status).toBe(401);
    expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("falls through with the original 401 when token refresh itself fails", async () => {
    mockGetState.mockReturnValue({
      oauthAccessToken: "token",
      refreshAccessToken: mockRefreshAccessToken,
    });
    mockRefreshAccessToken.mockRejectedValueOnce(new Error("refresh failed"));
    mockFetch.mockResolvedValueOnce(err(401));

    const response = await authedFetch(url);

    expect(response.status).toBe(401);
    expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("propagates network errors from the underlying fetch", async () => {
    setupTokens("token");
    mockFetch.mockRejectedValueOnce(new Error("Network failure"));

    await expect(authedFetch(url)).rejects.toThrow("Network failure");
  });

  it("merges caller-provided headers with the auth headers", async () => {
    setupTokens("my-token");
    mockFetch.mockResolvedValueOnce(ok());

    await authedFetch(url, {
      method: "POST",
      headers: { "X-Custom": "value" },
      body: "{}",
    });

    const init = mockFetch.mock.calls[0][1];
    expect(init.method).toBe("POST");
    expect(init.body).toBe("{}");
    expect(init.headers.Authorization).toBe("Bearer my-token");
    expect(init.headers["X-Custom"]).toBe("value");
  });

  it("dedups concurrent refreshes so only one fires on a 401 stampede", async () => {
    let current = "old-token";
    let resolveRefresh: () => void = () => {};
    const refreshPromise = new Promise<void>((resolve) => {
      resolveRefresh = () => {
        current = "new-token";
        resolve();
      };
    });
    mockRefreshAccessToken.mockImplementation(() => refreshPromise);
    mockGetState.mockImplementation(() => ({
      oauthAccessToken: current,
      refreshAccessToken: mockRefreshAccessToken,
    }));

    mockFetch
      .mockResolvedValueOnce(err(401))
      .mockResolvedValueOnce(err(401))
      .mockResolvedValueOnce(err(401))
      .mockResolvedValueOnce(ok({ n: 1 }))
      .mockResolvedValueOnce(ok({ n: 2 }))
      .mockResolvedValueOnce(ok({ n: 3 }));

    const pending = Promise.all([
      authedFetch(url),
      authedFetch(url),
      authedFetch(url),
    ]);

    // Drain microtasks until all three callers have parked on the shared
    // refresh, then release it and let the retries complete.
    for (let i = 0; i < 20; i++) await Promise.resolve();
    resolveRefresh();
    const responses = await pending;

    expect(responses.every((r) => r.ok)).toBe(true);
    expect(mockRefreshAccessToken).toHaveBeenCalledTimes(1);
  });
});
