import { mkdtemp, readdir, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { McpAuthStorage } from "./auth-storage";

const URL_A = "https://mcp.example.com/mcp";
const URL_B = "https://other.example.com/mcp";

describe("McpAuthStorage", () => {
  let dir: string;
  let storage: McpAuthStorage;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "mcp-auth-"));
    storage = new McpAuthStorage(dir);
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("returns undefined for unknown servers", async () => {
    expect(await storage.read("nope")).toBeUndefined();
    expect(await storage.readForUrl("nope", URL_A)).toBeUndefined();
  });

  it("round-trips an entry", async () => {
    await storage.update("demo", URL_A, (entry) => {
      entry.tokens = { accessToken: "abc", refreshToken: "def" };
      entry.codeVerifier = "verifier";
    });
    const entry = await storage.readForUrl("demo", URL_A);
    expect(entry?.tokens?.accessToken).toBe("abc");
    expect(entry?.codeVerifier).toBe("verifier");
    expect(entry?.serverUrl).toBe(URL_A);
  });

  it("treats credentials for a different URL as absent", async () => {
    await storage.update("demo", URL_A, (entry) => {
      entry.tokens = { accessToken: "abc" };
    });
    expect(await storage.readForUrl("demo", URL_B)).toBeUndefined();
  });

  it("discards stale credentials when the URL changes on update", async () => {
    await storage.update("demo", URL_A, (entry) => {
      entry.tokens = { accessToken: "old" };
      entry.clientInfo = { clientId: "old-client" };
    });
    await storage.update("demo", URL_B, (entry) => {
      entry.codeVerifier = "fresh";
    });
    const entry = await storage.readForUrl("demo", URL_B);
    expect(entry?.tokens).toBeUndefined();
    expect(entry?.clientInfo).toBeUndefined();
    expect(entry?.codeVerifier).toBe("fresh");
  });

  it("clear removes the entry", async () => {
    await storage.update("demo", URL_A, (entry) => {
      entry.tokens = { accessToken: "abc" };
    });
    await storage.clear("demo");
    expect(await storage.read("demo")).toBeUndefined();
  });

  it("clearFields removes only the named fields", async () => {
    await storage.update("demo", URL_A, (entry) => {
      entry.tokens = { accessToken: "abc" };
      entry.clientInfo = { clientId: "client" };
      entry.oauthState = "state";
    });
    await storage.clearFields("demo", ["tokens", "oauthState"]);
    const entry = await storage.readForUrl("demo", URL_A);
    expect(entry?.tokens).toBeUndefined();
    expect(entry?.oauthState).toBeUndefined();
    expect(entry?.clientInfo?.clientId).toBe("client");
  });

  it("isolates servers from each other", async () => {
    await storage.update("one", URL_A, (entry) => {
      entry.tokens = { accessToken: "one-token" };
    });
    await storage.update("two", URL_A, (entry) => {
      entry.tokens = { accessToken: "two-token" };
    });
    expect((await storage.read("one"))?.tokens?.accessToken).toBe("one-token");
    expect((await storage.read("two"))?.tokens?.accessToken).toBe("two-token");
    const files = await readdir(dir);
    expect(files).toHaveLength(2);
  });

  it.each([
    ["no tokens", undefined, { hasTokens: false, expired: false }],
    [
      "valid tokens",
      { accessToken: "abc", expiresAt: Date.now() / 1000 + 3600 },
      { hasTokens: true, expired: false },
    ],
    [
      "expired tokens",
      { accessToken: "abc", expiresAt: Date.now() / 1000 - 60 },
      { hasTokens: true, expired: true },
    ],
    [
      "tokens without expiry",
      { accessToken: "abc" },
      { hasTokens: true, expired: false },
    ],
  ])("status reports %s", async (_label, tokens, expected) => {
    if (tokens) {
      await storage.update("demo", URL_A, (entry) => {
        entry.tokens = tokens;
      });
    }
    expect(await storage.status("demo")).toMatchObject(expected);
  });

  it("writes files with owner-only permissions", async () => {
    await storage.update("demo", URL_A, (entry) => {
      entry.tokens = { accessToken: "secret" };
    });
    if (process.platform === "win32") return;
    const files = await readdir(dir);
    const fileStat = await stat(join(dir, files[0] as string));
    expect(fileStat.mode & 0o077).toBe(0);
  });
});
