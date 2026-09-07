import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("expo-auth-session", () => ({
  makeRedirectUri: () => "posthog://callback",
  AuthRequest: class {},
}));

vi.mock("expo-web-browser", () => ({
  maybeCompleteAuthSession: () => {},
}));

import { refreshAccessToken, TokenRefreshError } from "./oauth";

const originalFetch = global.fetch;

function mockResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: `Status ${status}`,
    headers: { "Content-Type": "application/json" },
  });
}

describe("refreshAccessToken", () => {
  beforeEach(() => {
    global.fetch = vi.fn() as unknown as typeof fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("returns the parsed token response on success", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      mockResponse(200, { access_token: "fresh", expires_in: 3600 }),
    );

    const result = await refreshAccessToken("refresh", "us");

    expect(result.access_token).toBe("fresh");
  });

  it.each([
    { name: "401", status: 401, body: {} },
    { name: "403", status: 403, body: {} },
    {
      name: "400 invalid_grant",
      status: 400,
      body: { error: "invalid_grant" },
    },
    {
      name: "400 invalid_token",
      status: 400,
      body: { error: "invalid_token" },
    },
  ])("classifies $name as auth_error", async ({ status, body }) => {
    vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse(status, body));

    await expect(refreshAccessToken("refresh", "us")).rejects.toMatchObject({
      errorCode: "auth_error",
    });
  });

  it.each([
    { name: "invalid_client", body: { error: "invalid_client" } },
    { name: "invalid_request", body: { error: "invalid_request" } },
  ])("classifies a 400 $name as unknown_error", async ({ body }) => {
    vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse(400, body));

    await expect(refreshAccessToken("refresh", "us")).rejects.toMatchObject({
      errorCode: "unknown_error",
    });
  });

  it.each([500, 502, 503])(
    "classifies a %i as server_error",
    async (status) => {
      vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse(status, {}));

      await expect(refreshAccessToken("refresh", "us")).rejects.toMatchObject({
        errorCode: "server_error",
      });
    },
  );

  it("classifies a thrown fetch as network_error", async () => {
    vi.mocked(global.fetch).mockRejectedValueOnce(new Error("offline"));

    const error = await refreshAccessToken("refresh", "us").catch((e) => e);

    expect(error).toBeInstanceOf(TokenRefreshError);
    expect(error.errorCode).toBe("network_error");
  });
});
