import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";
import { describe, expect, it } from "vitest";
import { buildLoopSavedProps, buildLoopViewedProps } from "./loopAnalytics";

function notificationChannel(
  enabled: boolean,
): LoopSchemas.LoopNotificationChannel {
  return { enabled, params: {} };
}

function trigger(
  type: LoopSchemas.LoopTriggerTypeEnum,
): LoopSchemas.LoopTrigger {
  return {
    id: `trigger-${type}`,
    loop_id: "loop-1",
    type,
    enabled: true,
    config: {},
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
  };
}

function loop(overrides: Partial<LoopSchemas.Loop> = {}): LoopSchemas.Loop {
  return {
    id: "loop-1",
    team_id: 1,
    created_by_id: 1,
    name: "Nightly triage",
    description: "",
    instructions: "triage the inbox",
    runtime_adapter: "claude",
    model: "",
    reasoning_effort: null,
    repositories: [],
    enabled: true,
    notifications: {
      email: notificationChannel(false),
      slack: notificationChannel(false),
    },
    context_target: null,
    last_run_at: null,
    last_run_status: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    triggers: [],
    ...overrides,
  };
}

describe("trigger flags", () => {
  it.each([
    {
      name: "no triggers",
      types: [] as LoopSchemas.LoopTriggerTypeEnum[],
      expected: {
        trigger_count: 0,
        has_schedule_trigger: false,
        has_github_trigger: false,
      },
    },
    {
      name: "schedule only",
      types: ["schedule"] as LoopSchemas.LoopTriggerTypeEnum[],
      expected: {
        trigger_count: 1,
        has_schedule_trigger: true,
        has_github_trigger: false,
      },
    },
    {
      name: "github only",
      types: ["github"] as LoopSchemas.LoopTriggerTypeEnum[],
      expected: {
        trigger_count: 1,
        has_schedule_trigger: false,
        has_github_trigger: true,
      },
    },
  ])("$name", ({ types, expected }) => {
    const props = buildLoopViewedProps(
      loop({ triggers: types.map(trigger) }),
      0,
    );
    expect(props).toMatchObject(expected);
  });
});

describe("buildLoopViewedProps", () => {
  it("omits model when the loop uses the adapter default", () => {
    expect(buildLoopViewedProps(loop({ model: "" }), 0).model).toBeUndefined();
  });

  it("passes a pinned model through", () => {
    expect(buildLoopViewedProps(loop({ model: "gpt-5" }), 0).model).toBe(
      "gpt-5",
    );
  });

  it("carries loop state and the given run count", () => {
    const props = buildLoopViewedProps(
      loop({
        enabled: false,
        reasoning_effort: "high",
        repositories: [{ github_integration_id: 1, full_name: "posthog/code" }],
        last_run_status: "failed",
      }),
      7,
    );
    expect(props).toMatchObject({
      loop_id: "loop-1",
      enabled: false,
      reasoning_effort: "high",
      repository_count: 1,
      last_run_status: "failed",
      recent_run_count: 7,
    });
  });
});

describe("buildLoopSavedProps", () => {
  it.each([
    { name: "none enabled", email: false, slack: false, expected: 0 },
    { name: "one enabled", email: true, slack: false, expected: 1 },
    { name: "both enabled", email: true, slack: true, expected: 2 },
  ])("counts notification channels: $name", ({ email, slack, expected }) => {
    const props = buildLoopSavedProps(
      loop({
        notifications: {
          email: notificationChannel(email),
          slack: notificationChannel(slack),
        },
      }),
    );
    expect(props.notification_channel_count).toBe(expected);
  });

  it.each([
    {
      name: "attached",
      context_target: { channel_id: "f1", name: "growth" },
      expected: true,
    },
    { name: "unattached", context_target: null, expected: false },
  ])("has_context_target when $name", ({ context_target, expected }) => {
    expect(
      buildLoopSavedProps(loop({ context_target })).has_context_target,
    ).toBe(expected);
  });

  it("omits model when the loop uses the adapter default", () => {
    expect(buildLoopSavedProps(loop({ model: "" })).model).toBeUndefined();
  });
});
