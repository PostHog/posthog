import { describe, expect, it } from "vitest";
import { OAUTH_SCOPE_VERSION, OAUTH_SCOPES } from "./oauth";

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
        "fingerprint": 1415029434,
        "scopeCount": 207,
        "scopeVersion": 8,
      }
    `);
  });

  // Structural guards that catch drift cheaply, independent of the exact list.
  // OAUTH_SCOPES must mirror OAUTH_SCOPES_SUPPORTED in the API's generated
  // services/mcp/src/lib/oauth-scopes.generated.ts (plus the privileged gateway
  // scopes); this repo can't assert cross-repo equality, so these check the shape invariants.
  it("contains no duplicate scopes", () => {
    expect(OAUTH_SCOPES.length).toBe(new Set(OAUTH_SCOPES).size);
  });

  it("includes each privileged gateway scope exactly once, kept last", () => {
    for (const scope of ["llm_gateway:read", "llm_gateway:write"]) {
      expect(
        OAUTH_SCOPES.filter((candidate) => candidate === scope),
      ).toHaveLength(1);
    }
    expect(OAUTH_SCOPES.slice(-2)).toEqual([
      "llm_gateway:read",
      "llm_gateway:write",
    ]);
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
