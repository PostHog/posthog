import type { ScoutOutputDestinations } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  buildMemberTargetValue,
  dedupeMemberTargets,
  deriveSlackTargetMode,
  describeSlackDelivery,
  MAX_SCOUT_SLACK_DM_TARGETS,
  mergeVisibleMembers,
  parseMemberIdFromTargetValue,
  parseMemberNameFromTargetValue,
  writeSlackDestination,
} from "./scoutSlackDestination";

describe("scoutSlackDestination", () => {
  it.each([
    ["Ada", "U123|@Ada"],
    // Slack display names are free text, so a name can contain its own `|`.
    ["Ops | EMEA", "U123|@Ops | EMEA"],
  ])("builds and parses the %j member target round trip", (name, target) => {
    const built = buildMemberTargetValue("U123", name);
    expect(built).toBe(target);
    expect(parseMemberIdFromTargetValue(built)).toBe("U123");
    expect(parseMemberNameFromTargetValue(built)).toBe(name);
  });

  it("does not double the leading @ on a display name", () => {
    expect(buildMemberTargetValue("U123", "@Ada")).toBe("U123|@Ada");
  });

  it.each([
    [null, "channel" as const],
    [{ integration_id: 1, channel: "C1|#eng" }, "channel" as const],
    [{ integration_id: 1, users: ["U1|@a"] }, "dm" as const],
    [{ integration_id: 1, users: [] }, "channel" as const],
  ])("derives the target mode from %j", (destination, expected) => {
    expect(deriveSlackTargetMode(destination)).toBe(expected);
  });

  it("dedupes by member ID and caps the list", () => {
    const targets = Array.from(
      { length: MAX_SCOUT_SLACK_DM_TARGETS + 2 },
      (_, i) => `U${i}|@user${i}`,
    );
    targets.push("U0|@duplicate");
    const deduped = dedupeMemberTargets(targets);
    expect(deduped).toHaveLength(MAX_SCOUT_SLACK_DM_TARGETS);
    expect(deduped[0]).toBe("U0|@user0");
    expect(new Set(deduped.map(parseMemberIdFromTargetValue)).size).toBe(
      MAX_SCOUT_SLACK_DM_TARGETS,
    );
  });

  it("keeps selected members that the fetched page omits", () => {
    const members = mergeVisibleMembers(
      [{ id: "U1", name: "one", display_name: "One" }],
      ["U1|@One", "U2|@Two"],
    );
    expect(members.map((m) => m.id)).toEqual(["U1", "U2"]);
    expect(members[1]).toEqual({ id: "U2", name: "Two", display_name: "Two" });
  });

  it("carries the webhook forward when writing a Slack destination", () => {
    const existing: ScoutOutputDestinations = {
      slack: { integration_id: 1, channel: "C1|#eng" },
      webhook: { hog_function_id: "hf_1" },
    };
    const next = writeSlackDestination(existing, {
      integration_id: 1,
      users: ["U1|@One"],
    });
    expect(next).toEqual({
      slack: { integration_id: 1, users: ["U1|@One"] },
      webhook: { hog_function_id: "hf_1" },
    });
  });

  it("drops Slack but keeps the webhook when cleared", () => {
    const existing: ScoutOutputDestinations = {
      slack: { integration_id: 1, channel: "C1|#eng" },
      webhook: { hog_function_id: "hf_1" },
    };
    expect(writeSlackDestination(existing, null)).toEqual({
      webhook: { hog_function_id: "hf_1" },
    });
  });

  it("returns an empty object when there is nothing to keep", () => {
    expect(writeSlackDestination(null, null)).toEqual({});
  });

  it.each([
    [null, "off" as const],
    [{ slack: null }, "off" as const],
    [{ slack: { integration_id: 1, channel: "C1|#eng" } }, "channel" as const],
    [{ slack: { integration_id: 1, users: ["U1|@a"] } }, "dm" as const],
  ])("describes the delivery kind of %j", (destinations, expected) => {
    expect(describeSlackDelivery(destinations)).toBe(expected);
  });
});
