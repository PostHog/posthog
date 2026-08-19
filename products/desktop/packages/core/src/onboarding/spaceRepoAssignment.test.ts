import { describe, expect, it } from "vitest";
import {
  type AssignableChannel,
  planSpaceRepoAssignments,
  resolveRepoIntegrationId,
} from "./spaceRepoAssignment";

function channel(overrides: Partial<AssignableChannel>): AssignableChannel {
  return {
    id: "id",
    name: "name",
    channel_type: "public",
    system_role: null,
    ...overrides,
  };
}

const personal = channel({
  id: "personal-id",
  name: "me",
  channel_type: "personal",
  system_role: "personal",
});
const general = channel({
  id: "general-id",
  name: "general",
  system_role: "general",
});

describe("spaceRepoAssignment", () => {
  describe("planSpaceRepoAssignments", () => {
    it("targets the personal space and a just-created empty #general", () => {
      expect(planSpaceRepoAssignments([personal, general], true)).toEqual([
        "personal-id",
        "general-id",
      ]);
    });

    it("skips an inherited #general even when its repository list is empty", () => {
      // A teammate may have emptied it on purpose; empty is not the same
      // signal as just created.
      expect(planSpaceRepoAssignments([personal, general], false)).toEqual([
        "personal-id",
      ]);
    });

    it("skips a just-created #general that a teammate already configured", () => {
      const configured = channel({
        ...general,
        repositories: ["example/app"],
      });
      expect(planSpaceRepoAssignments([personal, configured], true)).toEqual([
        "personal-id",
      ]);
    });

    it("returns no targets when neither space exists", () => {
      expect(
        planSpaceRepoAssignments(
          [channel({ id: "other", name: "random" })],
          true,
        ),
      ).toEqual([]);
    });
  });

  describe("resolveRepoIntegrationId", () => {
    const integrations = [
      { id: 1, config: { account: { name: "ExampleOrg" } } },
      { id: 2, config: { account: { name: "other" } } },
    ];

    it("matches the repo owner to the integration account", () => {
      expect(resolveRepoIntegrationId("exampleorg/app", integrations)).toBe(1);
    });

    it("falls back to a sole integration when the owner does not match", () => {
      expect(resolveRepoIntegrationId("unrelated/app", [integrations[0]])).toBe(
        1,
      );
    });

    it("refuses to guess between several non-matching integrations", () => {
      expect(resolveRepoIntegrationId("unrelated/app", integrations)).toBe(
        null,
      );
    });
  });
});
