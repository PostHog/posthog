import type {
  SignalTeamConfig,
  SignalUserAutonomyConfig,
} from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  effectivePullRequestReadyState,
  pullRequestReadyChoiceToValue,
  teamPullRequestReadyState,
  userPullRequestReadyChoice,
} from "./pullRequestReadyState";

function teamConfig(ready: boolean | undefined): SignalTeamConfig {
  return {
    id: "team-config",
    default_autostart_priority: "P2",
    default_open_pull_request_ready: ready,
    created_at: "2026-09-11T00:00:00Z",
    updated_at: "2026-09-11T00:00:00Z",
  };
}

function userConfig(
  ready: boolean | null | undefined,
): SignalUserAutonomyConfig {
  return {
    autostart_priority: null,
    github_open_pull_request_ready: ready,
  };
}

describe("pullRequestReadyState", () => {
  it.each([
    { config: teamConfig(true), expected: "ready" as const },
    { config: teamConfig(false), expected: "draft" as const },
    { config: teamConfig(undefined), expected: "draft" as const },
    { config: null, expected: "draft" as const },
  ])("reads the project default as $expected", ({ config, expected }) => {
    expect(teamPullRequestReadyState(config)).toBe(expected);
  });

  it.each([
    { config: userConfig(true), expected: "ready" as const },
    { config: userConfig(false), expected: "draft" as const },
    { config: userConfig(null), expected: "default" as const },
    { config: userConfig(undefined), expected: "default" as const },
    { config: null, expected: "default" as const },
  ])("reads my choice as $expected", ({ config, expected }) => {
    expect(userPullRequestReadyChoice(config)).toBe(expected);
  });

  it.each([
    { choice: "ready" as const, expected: true },
    { choice: "draft" as const, expected: false },
    { choice: "default" as const, expected: null },
  ])("saves $choice as $expected", ({ choice, expected }) => {
    expect(pullRequestReadyChoiceToValue(choice)).toBe(expected);
  });

  it("lets my draft choice override a project that opens ready", () => {
    expect(
      effectivePullRequestReadyState(teamConfig(true), userConfig(false)),
    ).toBe("draft");
  });

  it("follows the project when I have no preference", () => {
    expect(
      effectivePullRequestReadyState(teamConfig(true), userConfig(null)),
    ).toBe("ready");
  });
});
