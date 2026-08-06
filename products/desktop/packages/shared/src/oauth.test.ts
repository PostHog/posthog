import { describe, expect, it } from "vitest";
import {
  findMissingRequiredScopes,
  OAUTH_REQUIRED_SCOPES,
  OAUTH_SCOPE_VERSION,
  OAUTH_SCOPES,
} from "./oauth";

describe("OAUTH_SCOPES guard", () => {
  // Fingerprint instead of snapshotting the whole list: any add, removal, or reorder of
  // OAUTH_SCOPES changes the count or fingerprint and fails this test. When it fails, bump
  // OAUTH_SCOPE_VERSION (and update the expected values) so existing installs are forced to
  // re-authorize with the new set.
  it("fails when OAUTH_SCOPES changes — bump OAUTH_SCOPE_VERSION", () => {
    const fingerprint = OAUTH_SCOPES.reduce((hash, scope) => {
      for (let i = 0; i < scope.length; i++) {
        hash = (Math.imul(31, hash) + scope.charCodeAt(i)) | 0;
      }
      return hash;
    }, 0);

    expect({
      scopeVersion: OAUTH_SCOPE_VERSION,
      scopeCount: OAUTH_SCOPES.length,
      fingerprint,
    }).toMatchInlineSnapshot(`
      {
        "fingerprint": -237404099,
        "scopeCount": 206,
        "scopeVersion": 7,
      }
    `);
  });

  // Structural guards that catch drift cheaply, independent of the exact list.
  // OAUTH_SCOPES must mirror OAUTH_SCOPES_SUPPORTED in the API's generated
  // services/mcp/src/lib/oauth-scopes.generated.ts (plus llm_gateway:read); this
  // repo can't assert cross-repo equality, so these check the shape invariants.
  it("contains no duplicate scopes", () => {
    expect(OAUTH_SCOPES.length).toBe(new Set(OAUTH_SCOPES).size);
  });

  it("includes the privileged llm_gateway:read scope exactly once, kept last", () => {
    expect(
      OAUTH_SCOPES.filter((scope) => scope === "llm_gateway:read"),
    ).toHaveLength(1);
    expect(OAUTH_SCOPES.at(-1)).toBe("llm_gateway:read");
  });

  it("only contains well-formed scope strings", () => {
    const openidConnectScopes = new Set(["openid", "profile", "email"]);
    const malformed = OAUTH_SCOPES.filter(
      (scope) =>
        !openidConnectScopes.has(scope) &&
        !/^[a-z_]+:(read|write)$/.test(scope),
    );
    expect(malformed).toEqual([]);
  });
});

describe("findMissingRequiredScopes", () => {
  it.each([
    ["an absent scope string", undefined, []],
    ["an empty scope string", "", []],
    ["a wildcard grant", "*", []],
    ["both halves granted", "task:read task:write insight:read", []],
    ["the write half alone", "task:write", []],
    ["the read half alone", "task:read", ["task:write"]],
    [
      "no task scopes at all",
      "insight:read person:read",
      ["task:read", "task:write"],
    ],
  ] as const)("resolves %s", (_case, granted, expected) => {
    expect(findMissingRequiredScopes(granted)).toEqual(expected);
  });

  // A required scope the app never asks for would nag every install to re-authenticate over a
  // grant the server was never going to widen.
  it("only requires scopes the app actually requests", () => {
    const unrequested = OAUTH_REQUIRED_SCOPES.filter(
      (scope) => !OAUTH_SCOPES.includes(scope),
    );
    expect(unrequested).toEqual([]);
  });
});
