import type { SlackChannelOption } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  buildChannelTargetValue,
  deriveEffectiveIntegrationId,
  getSlackIntegrationLabel,
  mergeVisibleChannels,
  parseChannelIdFromTargetValue,
  parseChannelNameFromTargetValue,
} from "./slackNotificationTarget";

describe("channel target value encode/decode", () => {
  it("round-trips id and name", () => {
    const target = buildChannelTargetValue("C123", "general");
    expect(target).toBe("C123|#general");
    expect(parseChannelIdFromTargetValue(target)).toBe("C123");
    expect(parseChannelNameFromTargetValue(target)).toBe("general");
  });

  it("does not double-prefix the hash", () => {
    expect(buildChannelTargetValue("C1", "#dev")).toBe("C1|#dev");
  });

  it("returns null for empty values", () => {
    expect(parseChannelIdFromTargetValue(null)).toBeNull();
    expect(parseChannelNameFromTargetValue(undefined)).toBeNull();
  });
});

describe("getSlackIntegrationLabel", () => {
  it("prefers display_name", () => {
    expect(getSlackIntegrationLabel({ id: 1, display_name: "Acme" })).toBe(
      "Acme",
    );
  });

  it("falls back to account name then id", () => {
    expect(
      getSlackIntegrationLabel({ id: 2, config: { account: { name: "Org" } } }),
    ).toBe("Org");
    expect(getSlackIntegrationLabel({ id: 3 })).toBe("Slack workspace 3");
  });
});

describe("deriveEffectiveIntegrationId", () => {
  it("returns the selected id when set", () => {
    expect(deriveEffectiveIntegrationId(5, [{ id: 1 }, { id: 2 }])).toBe(5);
  });

  it("defaults to the only integration when none selected", () => {
    expect(deriveEffectiveIntegrationId(null, [{ id: 9 }])).toBe(9);
  });

  it("returns null when none selected and multiple exist", () => {
    expect(
      deriveEffectiveIntegrationId(null, [{ id: 1 }, { id: 2 }]),
    ).toBeNull();
  });
});

describe("mergeVisibleChannels", () => {
  const channel = (id: string): SlackChannelOption =>
    ({ id, name: id }) as unknown as SlackChannelOption;

  it("injects the configured channel when missing", () => {
    const merged = mergeVisibleChannels([channel("a")], "b", "beta");
    expect(merged.map((c) => c.id)).toEqual(["b", "a"]);
  });

  it("does not inject when already present", () => {
    const merged = mergeVisibleChannels([channel("b")], "b", "beta");
    expect(merged.map((c) => c.id)).toEqual(["b"]);
  });
});
