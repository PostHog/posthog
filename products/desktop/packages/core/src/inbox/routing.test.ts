import { describe, expect, it } from "vitest";
import type { InboxScope } from "./reportMembership";
import { ownershipScopeParams } from "./routing";

describe("ownership scopes", () => {
  it.each([
    ["for-you", { scope: "for_me" }],
    ["entire-project", { scope: "entire_project" }],
    ["team:commerce", { scope: "team", owning_role_id: "commerce" }],
    ["domain:checkout", { scope: "domain", domain_id: "checkout" }],
    ["teammate:person", { scope: "teammate", teammate_uuid: "person" }],
    ["unclassified", { scope: "unclassified" }],
  ] as const)(
    "sends %s to the authoritative backend scope",
    (scope, expected) => {
      expect(ownershipScopeParams(scope as InboxScope)).toEqual(expected);
      expect(ownershipScopeParams(scope as InboxScope)).not.toHaveProperty(
        "suggested_reviewers",
      );
    },
  );
});
