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
  const bothCreated = { personalCreated: true, generalCreated: true };
  const nothingCreated = { personalCreated: false, generalCreated: false };

  describe("planSpaceRepoAssignments", () => {
    it("targets both just-created spaces", () => {
      expect(
        planSpaceRepoAssignments([personal, general], bothCreated),
      ).toEqual(["personal-id", "general-id"]);
    });

    it("still fills an unconfigured pre-existing personal space", () => {
      expect(
        planSpaceRepoAssignments([personal, general], nothingCreated),
      ).toEqual(["personal-id"]);
    });

    it("keeps a configured personal space on re-onboarding", () => {
      // Wiped local storage re-runs onboarding; the pick must not clobber the
      // repos the user already configured on their own space.
      const configured = channel({
        ...personal,
        repositories: ["example/mine"],
      });
      expect(
        planSpaceRepoAssignments([configured, general], nothingCreated),
      ).toEqual([]);
    });

    it("skips an inherited #general even when its repository list is empty", () => {
      expect(
        planSpaceRepoAssignments([personal, general], {
          personalCreated: true,
          generalCreated: false,
        }),
      ).toEqual(["personal-id"]);
    });

    it("skips a just-created #general that a teammate already configured", () => {
      const configured = channel({
        ...general,
        repositories: ["example/app"],
      });
      expect(
        planSpaceRepoAssignments([personal, configured], bothCreated),
      ).toEqual(["personal-id"]);
    });

    it("returns no targets when neither space exists", () => {
      expect(
        planSpaceRepoAssignments(
          [channel({ id: "other", name: "random" })],
          bothCreated,
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
