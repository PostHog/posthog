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
        "fingerprint": 42,
        "scopeCount": 1,
        "scopeVersion": 5,
      }
    `);
  });

  it("requests the grandfathered wildcard grant", () => {
    expect(OAUTH_SCOPES).toEqual(["*"]);
  });
});
