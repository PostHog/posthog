import type { LoopSchemas } from "@posthog/api-client/loops";
import { describe, expect, it } from "vitest";
import {
  buildLoopEnabledToggledProps,
  buildLoopSavedProps,
  buildLoopViewedProps,
} from "./loopAnalytics";

function notificationChannel(
  enabled: boolean,
): LoopSchemas.LoopNotificationChannel {
  return { enabled, events: [], params: {} };
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
    schedule_sync_status: null,
    last_fired_at: null,
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
    visibility: "personal",
    instructions: "triage the inbox",
    runtime_adapter: "claude",
    model: "",
    reasoning_effort: null,
    repositories: [],
    sandbox_environment_id: null,
    enabled: true,
    disabled_reason: null,
    overlap_policy: "skip",
    behaviors: {
      create_prs: false,
      watch_ci: false,
      fix_review_comments: false,
      max_fix_iterations: 0,
    },
    connectors: { mcp_installation_ids: [], posthog_mcp_scopes: "read_only" },
    notifications: {
      push: notificationChannel(false),
      email: notificationChannel(false),
      slack: notificationChannel(false),
    },
    context_target: null,
    internal: false,
    origin_product: "user_created",
    last_run_at: null,
    last_run_status: null,
    last_error: null,
    consecutive_failures: 0,
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
        has_api_trigger: false,
      },
    },
    {
      name: "schedule only",
      types: ["schedule"] as LoopSchemas.LoopTriggerTypeEnum[],
      expected: {
        trigger_count: 1,
        has_schedule_trigger: true,
        has_github_trigger: false,
        has_api_trigger: false,
      },
    },
    {
      name: "github only",
      types: ["github"] as LoopSchemas.LoopTriggerTypeEnum[],
      expected: {
        trigger_count: 1,
        has_schedule_trigger: false,
        has_github_trigger: true,
        has_api_trigger: false,
      },
    },
    {
      name: "api only",
      types: ["api"] as LoopSchemas.LoopTriggerTypeEnum[],
      expected: {
        trigger_count: 1,
        has_schedule_trigger: false,
        has_github_trigger: false,
        has_api_trigger: true,
      },
    },
    {
      name: "duplicate type keeps raw count",
      types: ["schedule", "schedule"] as LoopSchemas.LoopTriggerTypeEnum[],
      expected: {
        trigger_count: 2,
        has_schedule_trigger: true,
        has_github_trigger: false,
        has_api_trigger: false,
      },
    },
    {
      name: "all types",
      types: ["schedule", "github", "api"] as LoopSchemas.LoopTriggerTypeEnum[],
      expected: {
        trigger_count: 3,
        has_schedule_trigger: true,
        has_github_trigger: true,
        has_api_trigger: true,
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
        visibility: "team",
        enabled: false,
        disabled_reason: "repeated_failures",
        reasoning_effort: "high",
        repositories: [{ github_integration_id: 1, full_name: "posthog/code" }],
        last_run_status: "failed",
        consecutive_failures: 3,
      }),
      7,
    );
    expect(props).toMatchObject({
      loop_id: "loop-1",
      visibility: "team",
      enabled: false,
      disabled_reason: "repeated_failures",
      reasoning_effort: "high",
      repository_count: 1,
      last_run_status: "failed",
      consecutive_failures: 3,
      recent_run_count: 7,
    });
  });
});

describe("buildLoopSavedProps", () => {
  it.each([
    {
      name: "none enabled",
      push: false,
      email: false,
      slack: false,
      expected: 0,
    },
    {
      name: "one enabled",
      push: true,
      email: false,
      slack: false,
      expected: 1,
    },
    { name: "two enabled", push: false, email: true, slack: true, expected: 2 },
    { name: "all enabled", push: true, email: true, slack: true, expected: 3 },
  ])(
    "counts notification channels: $name",
    ({ push, email, slack, expected }) => {
      const props = buildLoopSavedProps(
        loop({
          notifications: {
            push: notificationChannel(push),
            email: notificationChannel(email),
            slack: notificationChannel(slack),
          },
        }),
      );
      expect(props.notification_channel_count).toBe(expected);
    },
  );

  it.each([
    {
      name: "attached",
      context_target: {
        folder_id: "f1",
        name: "growth",
        outputs: { post_to_feed: true, update_context: false, canvas_id: null },
      },
      expected: true,
    },
    { name: "unattached", context_target: null, expected: false },
  ])("has_context_target when $name", ({ context_target, expected }) => {
    expect(
      buildLoopSavedProps(loop({ context_target })).has_context_target,
    ).toBe(expected);
  });

  it("mirrors behavior flags", () => {
    const props = buildLoopSavedProps(
      loop({
        behaviors: {
          create_prs: true,
          watch_ci: true,
          fix_review_comments: true,
          max_fix_iterations: 3,
        },
      }),
    );
    expect(props.is_pr_creation_enabled).toBe(true);
    expect(props.is_auto_fix_enabled).toBe(true);
  });

  it("omits model when the loop uses the adapter default", () => {
    expect(buildLoopSavedProps(loop({ model: "" })).model).toBeUndefined();
  });
});

describe("buildLoopEnabledToggledProps", () => {
  it.each([
    {
      name: "manual pause cleared",
      disabled_reason: null,
      enabled: true,
      success: true,
      was_auto_paused: false,
    },
    {
      name: "auto-pause cleared",
      disabled_reason: "usage_limited",
      enabled: true,
      success: true,
      was_auto_paused: true,
    },
    {
      name: "failed toggle",
      disabled_reason: null,
      enabled: false,
      success: false,
      was_auto_paused: false,
    },
  ])("$name", ({ disabled_reason, enabled, success, was_auto_paused }) => {
    expect(
      buildLoopEnabledToggledProps(loop({ disabled_reason }), enabled, success),
    ).toEqual({
      loop_id: "loop-1",
      enabled,
      visibility: "personal",
      was_auto_paused,
      success,
    });
  });
});
