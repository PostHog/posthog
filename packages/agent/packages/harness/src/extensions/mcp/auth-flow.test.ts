import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { generateState, runOAuthFlow } from "./auth-flow";
import { McpAuthStorage } from "./auth-storage";
import { CallbackServer } from "./callback-server";
import type { McpAuthConfig } from "./config";
import type { FakeOAuthServer } from "./test-support";
import { createFakeOAuthServer } from "./test-support";

// (browser simulation arms the fake's PKCE check; see browserFor below)

const SERVER_NAME = "demo";
const AUTH: McpAuthConfig = { type: "oauth" };

/**
 * Simulates the user's browser: parses the authorization URL the flow
 * produced, arms the fake server's PKCE check with the S256 challenge from
 * that URL, and follows the redirect back to the loopback callback with the
 * fake server's fixed code.
 */
function browserFor(
  oauth: FakeOAuthServer,
  result?: { code?: string; error?: string },
) {
  return async (authorizationUrl: string) => {
    const url = new URL(authorizationUrl);
    const redirectUri = url.searchParams.get("redirect_uri");
    const state = url.searchParams.get("state");
    if (!redirectUri || !state) {
      throw new Error("authorization URL missing redirect_uri or state");
    }
    // Arm real PKCE verification: the later code exchange must present a
    // code_verifier that hashes to this challenge.
    const challenge = url.searchParams.get("code_challenge");
    expect(url.searchParams.get("code_challenge_method")).toBe("S256");
    expect(challenge).toBeTruthy();
    oauth.setCodeChallenge(challenge);

    const callback = new URL(redirectUri);
    if (result?.error) {
      callback.searchParams.set("error", result.error);
    } else {
      callback.searchParams.set("code", result?.code ?? "test-code");
    }
    callback.searchParams.set("state", state);
    await fetch(callback);
  };
}

describe("generateState", () => {
  it("produces unique 64-char hex strings", () => {
    const a = generateState();
    const b = generateState();
    expect(a).toMatch(/^[0-9a-f]{64}$/);
    expect(a).not.toBe(b);
  });
});

describe("runOAuthFlow", () => {
  let dir: string;
  let storage: McpAuthStorage;
  let callbackServer: CallbackServer;
  let oauth: FakeOAuthServer;
  let serverUrl: string;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "mcp-flow-"));
    storage = new McpAuthStorage(dir);
    callbackServer = new CallbackServer();
    oauth = await createFakeOAuthServer();
    serverUrl = `${oauth.url}/mcp`;
  });

  afterEach(async () => {
    await callbackServer.stop();
    await oauth.close();
    await rm(dir, { recursive: true, force: true });
  });

  it("runs the full flow: discovery, registration, PKCE, code exchange", async () => {
    const onAuthorizationUrl = vi.fn();
    const result = await runOAuthFlow({
      serverName: SERVER_NAME,
      serverUrl,
      auth: AUTH,
      storage,
      callbackServer,
      openUrl: browserFor(oauth),
      onAuthorizationUrl,
      timeoutMs: 10_000,
    });

    expect(result).toBe("completed");
    expect(onAuthorizationUrl).toHaveBeenCalledTimes(1);

    // Dynamic registration happened with the callback server's redirect URL.
    expect(oauth.registrations).toHaveLength(1);
    const redirectUris = oauth.registrations[0]?.redirect_uris as string[];
    expect(redirectUris[0]).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/callback$/);

    // The code exchange used PKCE and the fixed code.
    const exchange = oauth.tokenRequests.find(
      (r) => r.grantType === "authorization_code",
    );
    expect(exchange).toMatchObject({ code: "test-code" });
    expect(exchange?.codeVerifier).toBeTruthy();

    // Tokens were persisted; the transient flow state was cleared.
    const entry = await storage.readForUrl(SERVER_NAME, serverUrl);
    expect(entry?.tokens?.accessToken).toBe("access-1");
    expect(entry?.tokens?.refreshToken).toBe("refresh-1");
    expect(entry?.oauthState).toBeUndefined();
    expect(entry?.clientInfo?.clientId).toBe("client-123");
  });

  it("returns authorized via silent refresh on a second run", async () => {
    await runOAuthFlow({
      serverName: SERVER_NAME,
      serverUrl,
      auth: AUTH,
      storage,
      callbackServer,
      openUrl: browserFor(oauth),
      timeoutMs: 10_000,
    });

    const openUrl = vi.fn();
    const result = await runOAuthFlow({
      serverName: SERVER_NAME,
      serverUrl,
      auth: AUTH,
      storage,
      callbackServer,
      openUrl,
      timeoutMs: 10_000,
    });

    expect(result).toBe("authorized");
    expect(openUrl).not.toHaveBeenCalled();
    const refresh = oauth.tokenRequests.find(
      (r) => r.grantType === "refresh_token",
    );
    expect(refresh?.refreshToken).toBe("refresh-1");
    const entry = await storage.readForUrl(SERVER_NAME, serverUrl);
    expect(entry?.tokens?.accessToken).toBe("access-2");
  });

  it("propagates authorization denial and clears the flow state", async () => {
    await expect(
      runOAuthFlow({
        serverName: SERVER_NAME,
        serverUrl,
        auth: AUTH,
        storage,
        callbackServer,
        openUrl: browserFor(oauth, { error: "access_denied" }),
        timeoutMs: 10_000,
      }),
    ).rejects.toThrowError(/access_denied/);

    const entry = await storage.read(SERVER_NAME);
    expect(entry?.oauthState).toBeUndefined();
    expect(entry?.tokens).toBeUndefined();
  });

  it("fails the exchange when the stored PKCE verifier is corrupted", async () => {
    // Proves the fake's S256 check has teeth: a verifier that no longer
    // matches the challenge sent during authorization must fail.
    await expect(
      runOAuthFlow({
        serverName: SERVER_NAME,
        serverUrl,
        auth: AUTH,
        storage,
        callbackServer,
        openUrl: async (authorizationUrl) => {
          const url = new URL(authorizationUrl);
          oauth.setCodeChallenge(url.searchParams.get("code_challenge"));
          // Corrupt the persisted verifier before the redirect lands.
          await storage.update(SERVER_NAME, serverUrl, (entry) => {
            entry.codeVerifier = "not-the-real-verifier";
          });
          const callback = new URL(
            url.searchParams.get("redirect_uri") as string,
          );
          callback.searchParams.set("code", "test-code");
          callback.searchParams.set(
            "state",
            url.searchParams.get("state") as string,
          );
          await fetch(callback);
        },
        timeoutMs: 10_000,
      }),
    ).rejects.toThrow();
    expect((await storage.read(SERVER_NAME))?.tokens).toBeUndefined();
  });

  it("fails the exchange for a wrong authorization code", async () => {
    await expect(
      runOAuthFlow({
        serverName: SERVER_NAME,
        serverUrl,
        auth: AUTH,
        storage,
        callbackServer,
        openUrl: browserFor(oauth, { code: "wrong-code" }),
        timeoutMs: 10_000,
      }),
    ).rejects.toThrow();
    const entry = await storage.read(SERVER_NAME);
    expect(entry?.tokens).toBeUndefined();
  });

  it("survives a browser that fails to open (headless)", async () => {
    // openUrl throws; a "user" then hits the callback manually.
    const flow = runOAuthFlow({
      serverName: SERVER_NAME,
      serverUrl,
      auth: AUTH,
      storage,
      callbackServer,
      openUrl: async () => {
        throw new Error("no browser available");
      },
      onAuthorizationUrl: (url) => {
        // Simulate the user completing auth out of band, slightly later.
        setTimeout(() => {
          void browserFor(oauth)(url);
        }, 20);
      },
      timeoutMs: 10_000,
    });
    await expect(flow).resolves.toBe("completed");
  });
});
