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
    it("fills empty default spaces", () => {
      expect(planSpaceRepoAssignments([personal, general])).toEqual([
        "personal-id",
        "general-id",
      ]);
    });

    it("keeps a configured personal space and fills empty general", () => {
      const configured = channel({
        ...personal,
        repositories: ["example/mine"],
      });
      expect(planSpaceRepoAssignments([configured, general])).toEqual([
        "general-id",
      ]);
    });

    it("keeps a configured general space and fills empty personal", () => {
      const configured = channel({
        ...general,
        repositories: ["example/app"],
      });
      expect(planSpaceRepoAssignments([personal, configured])).toEqual([
        "personal-id",
      ]);
    });

    it("returns no targets when neither space exists", () => {
      expect(
        planSpaceRepoAssignments([channel({ id: "other", name: "random" })]),
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
