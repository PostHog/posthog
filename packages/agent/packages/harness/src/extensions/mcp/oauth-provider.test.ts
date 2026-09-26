import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  auth,
  UnauthorizedError,
} from "@modelcontextprotocol/sdk/client/auth.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { McpAuthStorage } from "./auth-storage";
import type { McpAuthConfig } from "./config";
import { McpOAuthProvider } from "./oauth-provider";
import { createFakeOAuthServer } from "./test-support";

const SERVER = "demo";
const URL_A = "https://mcp.example.com/mcp";
const REDIRECT = "http://127.0.0.1:19876/callback";

function authConfig(overrides: Partial<McpAuthConfig> = {}): McpAuthConfig {
  return { type: "oauth", ...overrides };
}

describe("McpOAuthProvider", () => {
  let dir: string;
  let storage: McpAuthStorage;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "mcp-oauth-"));
    storage = new McpAuthStorage(dir);
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  function provider(
    config: McpAuthConfig = authConfig(),
    onRedirect?: (url: URL) => void,
    flowRedirectUrl?: string,
  ): McpOAuthProvider {
    return new McpOAuthProvider(
      SERVER,
      URL_A,
      config,
      storage,
      onRedirect,
      flowRedirectUrl,
    );
  }

  describe("clientMetadata", () => {
    it("describes an authorization_code + PKCE public client", () => {
      const metadata = provider(
        authConfig({ scope: "read write" }),
        undefined,
        REDIRECT,
      ).clientMetadata;
      expect(metadata).toMatchObject({
        redirect_uris: [REDIRECT],
        grant_types: ["authorization_code", "refresh_token"],
        response_types: ["code"],
        token_endpoint_auth_method: "none",
        scope: "read write",
      });
    });

    it("uses client_secret_post when a secret is configured", () => {
      const metadata = provider(
        authConfig({ clientSecret: "shh" }),
        undefined,
        REDIRECT,
      ).clientMetadata;
      expect(metadata.token_endpoint_auth_method).toBe("client_secret_post");
    });

    it("prefers the flow redirect URL over the configured one", () => {
      const p = provider(
        authConfig({ redirectUrl: "http://127.0.0.1:1111/cb" }),
        undefined,
        REDIRECT,
      );
      expect(p.redirectUrl).toBe(REDIRECT);
      expect(
        provider(authConfig({ redirectUrl: "http://127.0.0.1:1111/cb" }))
          .redirectUrl,
      ).toBe("http://127.0.0.1:1111/cb");
    });
  });

  describe("clientInformation", () => {
    it("prefers the pre-registered client from config", async () => {
      await storage.update(SERVER, URL_A, (entry) => {
        entry.clientInfo = { clientId: "stored-client" };
      });
      const info = await provider(
        authConfig({ clientId: "config-client", clientSecret: "s" }),
      ).clientInformation();
      expect(info).toEqual({
        client_id: "config-client",
        client_secret: "s",
      });
    });

    it("returns stored dynamic registration info", async () => {
      await storage.update(SERVER, URL_A, (entry) => {
        entry.clientInfo = { clientId: "stored-client" };
      });
      expect(await provider().clientInformation()).toEqual({
        client_id: "stored-client",
      });
    });

    it("ignores expired dynamic registrations (interactive mode)", async () => {
      await storage.update(SERVER, URL_A, (entry) => {
        entry.clientInfo = {
          clientId: "stored-client",
          clientSecretExpiresAt: Date.now() / 1000 - 60,
        };
      });
      expect(
        await provider(authConfig(), vi.fn()).clientInformation(),
      ).toBeUndefined();
    });

    it("returns undefined when nothing is stored (interactive mode)", async () => {
      expect(
        await provider(authConfig(), vi.fn()).clientInformation(),
      ).toBeUndefined();
    });

    it.each([
      ["nothing stored", undefined],
      [
        "expired registration",
        {
          clientId: "stored-client",
          clientSecretExpiresAt: Date.now() / 1000 - 60,
        },
      ],
    ])(
      "background mode throws UnauthorizedError with %s (never registers)",
      async (_label, clientInfo) => {
        if (clientInfo) {
          await storage.update(SERVER, URL_A, (entry) => {
            entry.clientInfo = clientInfo;
          });
        }
        await expect(provider().clientInformation()).rejects.toBeInstanceOf(
          UnauthorizedError,
        );
      },
    );
  });

  it("background redirectUrl is a truthy placeholder (SDK refresh-path requirement)", () => {
    expect(provider().redirectUrl).toBeTruthy();
  });

  describe("background provider through real SDK auth()", () => {
    it("silently refreshes stored tokens without registration or browser", async () => {
      const oauth = await createFakeOAuthServer();
      const serverUrl = `${oauth.url}/mcp`;
      await storage.update(SERVER, serverUrl, (entry) => {
        entry.clientInfo = { clientId: "client-123" };
        entry.tokens = { accessToken: "stale", refreshToken: "refresh-old" };
      });
      const p = new McpOAuthProvider(SERVER, serverUrl, authConfig(), storage);

      const result = await auth(p, { serverUrl });

      expect(result).toBe("AUTHORIZED");
      expect(oauth.registrations).toHaveLength(0);
      expect(oauth.tokenRequests).toEqual([
        expect.objectContaining({
          grantType: "refresh_token",
          refreshToken: "refresh-old",
        }),
      ]);
      const entry = await storage.readForUrl(SERVER, serverUrl);
      expect(entry?.tokens?.accessToken).toBe("access-1");
      await oauth.close();
    });

    it("fails with UnauthorizedError and no side effects when unauthenticated", async () => {
      const oauth = await createFakeOAuthServer();
      const serverUrl = `${oauth.url}/mcp`;
      const p = new McpOAuthProvider(SERVER, serverUrl, authConfig(), storage);

      await expect(auth(p, { serverUrl })).rejects.toBeInstanceOf(
        UnauthorizedError,
      );
      expect(oauth.registrations).toHaveLength(0);
      expect(oauth.tokenRequests).toHaveLength(0);
      await oauth.close();
    });

    it("fails with UnauthorizedError when tokens lack a refresh token", async () => {
      const oauth = await createFakeOAuthServer();
      const serverUrl = `${oauth.url}/mcp`;
      await storage.update(SERVER, serverUrl, (entry) => {
        entry.clientInfo = { clientId: "client-123" };
        entry.tokens = { accessToken: "expired-no-refresh" };
      });
      const p = new McpOAuthProvider(SERVER, serverUrl, authConfig(), storage);

      await expect(auth(p, { serverUrl })).rejects.toBeInstanceOf(
        UnauthorizedError,
      );
      expect(oauth.registrations).toHaveLength(0);
      expect(oauth.tokenRequests).toHaveLength(0);
      await oauth.close();
    });
  });

  it("saveClientInformation round-trips through storage", async () => {
    const p = provider();
    await p.saveClientInformation({
      client_id: "new-client",
      client_secret: "secret",
      redirect_uris: [REDIRECT],
    });
    expect(await p.clientInformation()).toEqual({
      client_id: "new-client",
      client_secret: "secret",
    });
    const entry = await storage.readForUrl(SERVER, URL_A);
    expect(entry?.clientInfo?.redirectUris).toEqual([REDIRECT]);
  });

  it("saveTokens/tokens round-trip with expiry conversion", async () => {
    const p = provider();
    await p.saveTokens({
      access_token: "access",
      token_type: "bearer",
      refresh_token: "refresh",
      expires_in: 3600,
      scope: "read",
    });
    const tokens = await p.tokens();
    expect(tokens).toMatchObject({
      access_token: "access",
      token_type: "Bearer",
      refresh_token: "refresh",
      scope: "read",
    });
    expect(tokens?.expires_in).toBeGreaterThan(3500);
    expect(tokens?.expires_in).toBeLessThanOrEqual(3600);
  });

  it("tokens are scoped to the server URL", async () => {
    await provider().saveTokens({ access_token: "a", token_type: "bearer" });
    const other = new McpOAuthProvider(
      SERVER,
      "https://different.example.com/mcp",
      authConfig(),
      storage,
    );
    expect(await other.tokens()).toBeUndefined();
  });

  describe("redirectToAuthorization guard", () => {
    const AUTH_URL = new URL("https://auth.example.com/authorize");

    it("throws UnauthorizedError for background providers", async () => {
      await expect(
        provider().redirectToAuthorization(AUTH_URL),
      ).rejects.toBeInstanceOf(UnauthorizedError);
    });

    it("throws UnauthorizedError when no interactive flow is in progress", async () => {
      const onRedirect = vi.fn();
      await expect(
        provider(authConfig(), onRedirect).redirectToAuthorization(AUTH_URL),
      ).rejects.toBeInstanceOf(UnauthorizedError);
      expect(onRedirect).not.toHaveBeenCalled();
    });

    it("forwards the URL during an interactive flow", async () => {
      await storage.update(SERVER, URL_A, (entry) => {
        entry.oauthState = "state-123";
      });
      const onRedirect = vi.fn();
      await provider(authConfig(), onRedirect).redirectToAuthorization(
        AUTH_URL,
      );
      expect(onRedirect).toHaveBeenCalledWith(AUTH_URL);
    });
  });

  it("state returns the stored flow state or throws", async () => {
    await expect(provider().state()).rejects.toBeInstanceOf(UnauthorizedError);
    await storage.update(SERVER, URL_A, (entry) => {
      entry.oauthState = "state-123";
    });
    expect(await provider().state()).toBe("state-123");
  });

  it("codeVerifier round-trips and throws when missing", async () => {
    const p = provider();
    await expect(p.codeVerifier()).rejects.toThrowError(
      /No PKCE code verifier/,
    );
    await p.saveCodeVerifier("verifier-1");
    expect(await p.codeVerifier()).toBe("verifier-1");
  });

  it.each([
    ["tokens", { tokens: undefined, clientInfo: "kept" }],
    ["client", { tokens: "kept", clientInfo: undefined }],
    ["all", { tokens: undefined, clientInfo: undefined }],
  ] as const)("invalidateCredentials(%s)", async (scope, expected) => {
    const p = provider();
    await p.saveTokens({ access_token: "a", token_type: "bearer" });
    await p.saveClientInformation({ client_id: "c", redirect_uris: [] });

    await p.invalidateCredentials(scope);
    const entry = await storage.read(SERVER);
    if (expected.tokens === undefined) {
      expect(entry?.tokens).toBeUndefined();
    } else {
      expect(entry?.tokens).toBeDefined();
    }
    if (expected.clientInfo === undefined) {
      expect(entry?.clientInfo).toBeUndefined();
    } else {
      expect(entry?.clientInfo).toBeDefined();
    }
  });
});
