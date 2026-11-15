import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";
import { systemTimezone } from "@posthog/ui/primitives/timezone";
import { describe, expect, it } from "vitest";
import {
  emptyLoopFormValues,
  githubTriggerActionOptions,
  isLoopFormValid,
  isTriggerDraftValid,
  type LoopFormValues,
  type LoopTriggerDraft,
  loopToFormValues,
  withGithubTriggerEvents,
} from "./loopFormTypes";

function scheduleTrigger(
  config: LoopSchemas.LoopScheduleTriggerConfig,
): LoopTriggerDraft {
  return { key: "k1", type: "schedule", enabled: true, config };
}

function githubTrigger(
  config: Partial<LoopSchemas.LoopGithubTriggerConfig> = {},
): LoopTriggerDraft {
  return {
    key: "k2",
    type: "github",
    enabled: true,
    config: {
      github_integration_id: 7,
      repository: "posthog/posthog",
      events: ["push"],
      ...config,
    },
  };
}

function validFormValues(): LoopFormValues {
  return {
    ...emptyLoopFormValues(),
    name: "Standup digest",
    instructions: "Summarize the day.",
  };
}

describe("isTriggerDraftValid", () => {
  it.each([
    {
      name: "schedule with a cron",
      trigger: scheduleTrigger({ cron_expression: "0 9 * * *" }),
      expected: true,
    },
    {
      name: "schedule with a run_at",
      trigger: scheduleTrigger({ run_at: "2026-07-16T10:00:00Z" }),
      expected: true,
    },
    {
      name: "schedule with neither cron nor run_at",
      trigger: scheduleTrigger({}),
      expected: false,
    },
    {
      name: "complete github trigger",
      trigger: githubTrigger(),
      expected: true,
    },
    {
      name: "github without repository",
      trigger: githubTrigger({ repository: "" }),
      expected: false,
    },
    {
      name: "github without integration id",
      trigger: githubTrigger({ github_integration_id: 0 }),
      expected: true,
    },
    {
      name: "github without events",
      trigger: githubTrigger({ events: [] }),
      expected: false,
    },
    {
      name: "github with two events",
      trigger: githubTrigger({ events: ["push", "issues"] }),
      expected: false,
    },
  ])("$name → $expected", ({ trigger, expected }) => {
    expect(isTriggerDraftValid(trigger)).toBe(expected);
  });
});

describe("githubTriggerActionOptions", () => {
  it.each<[string, LoopSchemas.LoopGithubTriggerEventEnum[], string[]]>([
    ["no events", [], []],
    ["push has no actions", ["push"], []],
    ["issue comments", ["issue_comment"], ["created", "edited", "deleted"]],
    // One `actions` list is matched against every event on the trigger, so offering an action
    // only some of them send would stop the others firing at all.
    [
      "two events share only some actions",
      ["issues", "issue_comment"],
      ["edited", "deleted"],
    ],
    ["anything paired with push", ["pull_request", "push"], []],
  ])("%s", (_label, events, expected) => {
    expect(githubTriggerActionOptions(events)).toEqual(expected);
  });
});

describe("withGithubTriggerEvents", () => {
  it("drops an action the newly selected events cannot all send", () => {
    // Ticking a second event while `review_requested` is selected would otherwise leave a
    // filter that no issue event can ever match, silently disabling it.
    const config: LoopSchemas.LoopGithubTriggerConfig = {
      github_integration_id: 7,
      repository: "posthog/posthog",
      events: ["pull_request"],
      filters: { actions: ["review_requested", "closed"] },
    };

    const next = withGithubTriggerEvents(config, ["pull_request", "issues"]);

    expect(next.filters?.actions).toEqual(["closed"]);
  });

  it("keeps an action it does not model", () => {
    // `locked` is a real pull_request action GITHUB_EVENT_ACTIONS omits, so it renders no chip.
    // Dropping it on an unrelated event toggle would silently widen the trigger to every action.
    const config: LoopSchemas.LoopGithubTriggerConfig = {
      github_integration_id: 7,
      repository: "posthog/posthog",
      events: ["pull_request"],
      filters: { actions: ["locked"] },
    };

    const next = withGithubTriggerEvents(config, ["pull_request", "issues"]);

    expect(next.filters?.actions).toEqual(["locked"]);
  });

  it("drops the filter key entirely when nothing survives", () => {
    const config: LoopSchemas.LoopGithubTriggerConfig = {
      github_integration_id: 7,
      repository: "posthog/posthog",
      events: ["pull_request"],
      filters: { actions: ["review_requested"] },
    };

    expect(
      withGithubTriggerEvents(config, ["push"]).filters,
    ).not.toHaveProperty("actions");
  });
});

describe("isLoopFormValid", () => {
  it("accepts a named form with instructions and one trigger", () => {
    expect(isLoopFormValid(validFormValues())).toBe(true);
  });

  it.each([
    { name: "blank name", patch: { name: "   " } },
    { name: "blank instructions", patch: { instructions: "\n" } },
    { name: "no trigger", patch: { triggers: [] } },
    {
      name: "a second trigger",
      patch: {
        triggers: [
          scheduleTrigger({ cron_expression: "0 9 * * *" }),
          githubTrigger(),
        ],
      },
    },
    {
      name: "a disabled trigger",
      patch: {
        triggers: [
          {
            ...scheduleTrigger({ cron_expression: "0 9 * * *" }),
            enabled: false,
          },
        ],
      },
    },
    {
      name: "an invalid trigger",
      patch: { triggers: [scheduleTrigger({})] },
    },
  ])("rejects $name", ({ patch }) => {
    expect(isLoopFormValid({ ...validFormValues(), ...patch })).toBe(false);
  });
});

describe("emptyLoopFormValues", () => {
  it("starts new loops with an enabled weekly schedule trigger", () => {
    expect(emptyLoopFormValues().triggers).toEqual([
      {
        key: expect.any(String),
        type: "schedule",
        enabled: true,
        config: {
          cron_expression: "0 9 * * 1",
          timezone: systemTimezone(),
        },
      },
    ]);
  });
});

describe("loopToFormValues", () => {
  it("maps a loop's trigger and space into form drafts", () => {
    const loop = {
      id: "loop-1",
      team_id: 1,
      created_by_id: 1,
      name: "Digest",
      description: "daily",
      instructions: "Summarize.",
      runtime_adapter: "claude",
      model: "claude-sonnet-5",
      reasoning_effort: "medium",
      repositories: [
        { github_integration_id: 7, full_name: "posthog/posthog" },
      ],
      enabled: true,
      notifications: {
        email: { enabled: false, params: {} },
        slack: { enabled: false, params: {} },
      },
      context_target: { channel_id: "f1", name: "growth" },
      last_run_at: null,
      last_run_status: null,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      triggers: [
        {
          id: "trigger",
          loop_id: "loop-1",
          type: "schedule",
          enabled: true,
          config: { cron_expression: "0 9 * * *", timezone: "UTC" },
          created_at: "2026-07-01T00:00:00Z",
          updated_at: "2026-07-01T00:00:00Z",
        },
      ],
    } satisfies LoopSchemas.Loop;

    const values = loopToFormValues(loop);
    expect(values.triggers).toEqual([
      {
        key: "trigger",
        type: "schedule",
        enabled: true,
        config: { cron_expression: "0 9 * * *", timezone: "UTC" },
      },
    ]);
    expect(values.contextTarget).toEqual({ folderId: "f1", name: "growth" });
  });
});
