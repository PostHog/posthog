import type { SignalTeamConfig } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  DEFAULT_PULL_REQUEST_LABEL,
  describePullRequestLabel,
  effectivePullRequestLabel,
  PULL_REQUEST_LABEL_MAX_LENGTH,
  parsePullRequestLabel,
  pullRequestLabelEnabled,
  pullRequestLabelFieldValue,
} from "./pullRequestLabel";

function config(overrides: Partial<SignalTeamConfig> = {}): SignalTeamConfig {
  return {
    id: "config-1",
    default_autostart_priority: "P2",
    pull_request_label_enabled: false,
    pull_request_label: null,
    created_at: "2026-09-20T00:00:00Z",
    updated_at: "2026-09-20T00:00:00Z",
    ...overrides,
  } as SignalTeamConfig;
}

describe("pullRequestLabel", () => {
  it.each([
    ["keeps a typed name", "release-bot", { ok: true, value: "release-bot" }],
    ["trims surrounding whitespace", "  ship  ", { ok: true, value: "ship" }],
    ["clears on empty input", "", { ok: true, value: null }],
    ["clears on whitespace-only input", "   ", { ok: true, value: null }],
  ])("%s", (_name, input, expected) => {
    expect(parsePullRequestLabel(input)).toEqual(expected);
  });

  it("rejects a name longer than GitHub accepts", () => {
    const result = parsePullRequestLabel(
      "x".repeat(PULL_REQUEST_LABEL_MAX_LENGTH + 1),
    );
    expect(result.ok).toBe(false);
  });

  it("reads the saved state off the config", () => {
    const saved = config({
      pull_request_label_enabled: true,
      pull_request_label: "ship-it",
    });
    expect(pullRequestLabelEnabled(saved)).toBe(true);
    expect(pullRequestLabelFieldValue(saved)).toBe("ship-it");
    expect(effectivePullRequestLabel(saved)).toBe("ship-it");
  });

  it.each([
    ["missing config", undefined, false, ""],
    ["disabled config", config(), false, ""],
    [
      "enabled without a name",
      config({ pull_request_label_enabled: true }),
      true,
      "",
    ],
  ])("reads %s", (_name, value, enabled, fieldValue) => {
    expect(pullRequestLabelEnabled(value)).toBe(enabled);
    expect(pullRequestLabelFieldValue(value)).toBe(fieldValue);
    expect(effectivePullRequestLabel(value)).toBe(DEFAULT_PULL_REQUEST_LABEL);
  });

  it("describes both states", () => {
    expect(describePullRequestLabel(config())).toContain("without a label");
    expect(
      describePullRequestLabel(config({ pull_request_label_enabled: true })),
    ).toContain(DEFAULT_PULL_REQUEST_LABEL);
  });
});
