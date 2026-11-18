import { afterEach, describe, expect, it } from "vitest";
import { CallbackServer, parseStaticRedirectUrl } from "./callback-server";

describe("parseStaticRedirectUrl", () => {
  it.each([
    [
      "http://127.0.0.1:19876/callback",
      { hostname: "127.0.0.1", port: 19876, path: "/callback" },
    ],
    [
      "http://localhost:8080/oauth/cb",
      { hostname: "localhost", port: 8080, path: "/oauth/cb" },
    ],
  ])("accepts %s", (url, expected) => {
    expect(parseStaticRedirectUrl(url)).toEqual(expected);
  });

  it.each([
    ["not a url", /Invalid OAuth redirectUrl/],
    ["https://127.0.0.1:19876/callback", /loopback/],
    ["http://example.com:19876/callback", /loopback/],
    ["http://127.0.0.1/callback", /explicit port/],
  ])("rejects %s", (url, message) => {
    expect(() => parseStaticRedirectUrl(url)).toThrowError(message);
  });
});

describe("CallbackServer", () => {
  const servers: CallbackServer[] = [];

  function makeServer(): CallbackServer {
    const server = new CallbackServer();
    servers.push(server);
    return server;
  }

  afterEach(async () => {
    await Promise.all(servers.splice(0).map((server) => server.stop()));
  });

  it("starts on an ephemeral loopback port by default", async () => {
    const server = makeServer();
    const endpoint = await server.ensureStarted();
    expect(endpoint.port).toBeGreaterThan(0);
    expect(endpoint.redirectUrl).toBe(
      `http://127.0.0.1:${endpoint.port}/callback`,
    );
  });

  it("reuses the running server on repeat ensureStarted", async () => {
    const server = makeServer();
    const first = await server.ensureStarted();
    const second = await server.ensureStarted();
    expect(second.port).toBe(first.port);
  });

  it("rebinds an idle server to a static redirect URL verbatim", async () => {
    // Learn a port by binding ephemerally, then rebind the same server to a
    // static URL on that port (avoids a probe-then-bind TOCTOU race — the
    // port is only ever released by the rebind itself).
    const server = makeServer();
    const first = await server.ensureStarted();
    const staticUrl = `http://127.0.0.1:${first.port}/custom/cb`;

    const endpoint = await server.ensureStarted(staticUrl);
    expect(endpoint.redirectUrl).toBe(staticUrl);

    const waiter = server.waitForCallback("s1", 5_000);
    const res = await fetch(`${staticUrl}?code=abc&state=s1`);
    expect(res.status).toBe(200);
    expect(await waiter).toBe("abc");

    // The old default path is gone after the rebind.
    const old = await fetch(`http://127.0.0.1:${first.port}/callback`);
    expect(old.status).toBe(404);
  });

  it("refuses to rebind while an authorization is pending", async () => {
    const server = makeServer();
    const { port } = await server.ensureStarted();
    const waiter = server.waitForCallback("s1", 5_000);

    await expect(
      server.ensureStarted(`http://127.0.0.1:${port}/other/path`),
    ).rejects.toThrowError(/cannot rebind while an authorization is pending/);

    server.cancel("s1");
    await expect(waiter).rejects.toThrowError(/cancelled/);
  });

  it("serializes concurrent ensureStarted calls onto one server", async () => {
    const server = makeServer();
    const [a, b, c] = await Promise.all([
      server.ensureStarted(),
      server.ensureStarted(),
      server.ensureStarted(),
    ]);
    expect(b?.port).toBe(a?.port);
    expect(c?.port).toBe(a?.port);
    expect(b?.redirectUrl).toBe(a?.redirectUrl);
  });

  it("resolves the matching waiter with the authorization code", async () => {
    const server = makeServer();
    const { redirectUrl } = await server.ensureStarted();
    const waiter = server.waitForCallback("state-1", 5_000);

    const res = await fetch(`${redirectUrl}?code=the-code&state=state-1`);
    expect(res.status).toBe(200);
    expect(await res.text()).toContain("Authorization successful");
    expect(await waiter).toBe("the-code");
  });

  it("rejects requests with unknown or missing state", async () => {
    const server = makeServer();
    const { redirectUrl } = await server.ensureStarted();
    const waiter = server.waitForCallback("real-state", 5_000);

    const unknown = await fetch(`${redirectUrl}?code=x&state=wrong`);
    expect(unknown.status).toBe(400);
    const missing = await fetch(`${redirectUrl}?code=x`);
    expect(missing.status).toBe(400);

    // The real waiter is untouched.
    server.cancel("real-state");
    await expect(waiter).rejects.toThrowError(/cancelled/);
  });

  it("rejects the waiter on an OAuth error response", async () => {
    const server = makeServer();
    const { redirectUrl } = await server.ensureStarted();
    const waiter = server.waitForCallback("state-1", 5_000);
    // Attach the expectation before the redirect lands so the rejection is
    // never observed as unhandled.
    const expectation = expect(waiter).rejects.toThrowError(
      /access_denied: User said no/,
    );

    const res = await fetch(
      `${redirectUrl}?error=access_denied&error_description=User+said+no&state=state-1`,
    );
    expect(res.status).toBe(200);
    await expectation;
  });

  it("returns 400 and rejects the waiter when the code is missing", async () => {
    // A malformed redirect (known state, no `code` and no `error`) must
    // reject the pending waiter immediately, not leave it hanging until
    // the 5-minute timeout with an unresponsive terminal.
    const server = makeServer();
    const { redirectUrl } = await server.ensureStarted();
    const waiter = server.waitForCallback("state-1", 5_000);
    // Attach the expectation before the redirect lands so the rejection is
    // never observed as unhandled.
    const expectation = expect(waiter).rejects.toThrowError(/code/);

    const res = await fetch(`${redirectUrl}?state=state-1`);
    expect(res.status).toBe(400);

    await expectation;
  });

  it("404s on other paths", async () => {
    const server = makeServer();
    const { port } = await server.ensureStarted();
    const res = await fetch(`http://127.0.0.1:${port}/other`);
    expect(res.status).toBe(404);
  });

  it("times out a waiter", async () => {
    const server = makeServer();
    await server.ensureStarted();
    await expect(server.waitForCallback("state-1", 10)).rejects.toThrowError(
      /timed out/,
    );
  });

  it("stop rejects all pending waiters and frees the port", async () => {
    const server = makeServer();
    const { redirectUrl } = await server.ensureStarted();
    const waiter = server.waitForCallback("state-1", 5_000);
    await server.stop();
    await expect(waiter).rejects.toThrowError(/cancelled/);
    await expect(
      fetch(`${redirectUrl}?code=x&state=state-1`),
    ).rejects.toThrow();
  });
});
