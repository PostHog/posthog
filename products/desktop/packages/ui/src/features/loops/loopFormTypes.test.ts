import type { LoopSchemas } from "@posthog/api-client/loops";
import { systemTimezone } from "@posthog/ui/primitives/timezone";
import { describe, expect, it } from "vitest";
import {
  defaultLoopBehaviors,
  emptyLoopFormValues,
  githubTriggerActionOptions,
  isAutoFixEnabled,
  isLoopFormValid,
  isTriggerDraftValid,
  type LoopFormValues,
  type LoopTriggerDraft,
  loopToFormValues,
  normalizeLoopFormValues,
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
      name: "github without integration id, since the workflow resolves the repository",
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
    {
      name: "github with a complete payload condition",
      trigger: githubTrigger({
        filters: {
          payload: [{ path: "requested_team.slug", equals: "team-security" }],
        },
      }),
      expected: true,
    },
    {
      name: "github with a payload condition missing its path",
      trigger: githubTrigger({
        filters: { payload: [{ path: " ", equals: "team-security" }] },
      }),
      expected: false,
    },
    {
      name: "github with a payload condition missing its value",
      trigger: githubTrigger({
        filters: { payload: [{ path: "requested_team.slug", equals: "" }] },
      }),
      expected: false,
    },
    {
      // A trailing separator is what a half-typed second value looks like; drop it rather
      // than blocking the form while someone is still writing.
      name: "github with a blank value alongside a real one",
      trigger: githubTrigger({
        filters: {
          payload: [{ path: "requested_team.slug", equals: ["a", " "] }],
        },
      }),
      expected: true,
    },
    {
      name: "api trigger, which a workflow cannot carry",
      trigger: {
        key: "k3",
        type: "api",
        enabled: true,
        config: {},
      } as LoopTriggerDraft,
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
    { name: "no triggers", patch: { triggers: [] } },
    {
      name: "two triggers",
      patch: {
        triggers: [
          scheduleTrigger({ cron_expression: "0 9 * * *" }),
          scheduleTrigger({ cron_expression: "0 10 * * *" }),
        ],
      },
    },
    {
      name: "context target on a personal loop",
      patch: {
        contextTarget: {
          folderId: "f1",
          name: "growth",
          outputs: {
            post_to_feed: true,
            update_context: false,
            canvas_id: null,
          },
        },
        visibility: "personal" as const,
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

describe("normalizeLoopFormValues", () => {
  it("forces team visibility when a context target is set", () => {
    const values = {
      ...validFormValues(),
      visibility: "personal" as const,
      contextTarget: {
        folderId: "f1",
        name: "growth",
        outputs: { post_to_feed: true, update_context: false, canvas_id: null },
      },
    };
    expect(normalizeLoopFormValues(values).visibility).toBe("team");
  });

  it("leaves unattached loops untouched", () => {
    const values = validFormValues();
    expect(normalizeLoopFormValues(values)).toBe(values);
  });
});

describe("loopToFormValues", () => {
  it("maps a loop's triggers and context target into form values", () => {
    const loop = {
      id: "loop-1",
      team_id: 1,
      created_by_id: 1,
      name: "Digest",
      description: "daily",
      visibility: "team",
      instructions: "Summarize.",
      runtime_adapter: "claude",
      model: "claude-sonnet-5",
      reasoning_effort: "medium",
      repositories: [
        { github_integration_id: 7, full_name: "posthog/posthog" },
      ],
      sandbox_environment_id: null,
      enabled: true,
      disabled_reason: null,
      overlap_policy: "skip",
      behaviors: defaultLoopBehaviors(),
      connectors: { mcp_installation_ids: [], posthog_mcp_scopes: "read_only" },
      notifications: {
        push: { enabled: false, events: [], params: {} },
        email: { enabled: false, events: [], params: {} },
        slack: { enabled: false, events: [], params: {} },
      },
      context_target: {
        folder_id: "f1",
        name: "growth",
        outputs: { post_to_feed: true, update_context: false, canvas_id: null },
      },
      internal: false,
      origin_product: "user_created",
      last_run_at: null,
      last_run_status: null,
      last_error: null,
      consecutive_failures: 0,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      triggers: [
        {
          id: "trigger-1",
          loop_id: "loop-1",
          type: "schedule",
          enabled: true,
          config: { cron_expression: "0 9 * * *", timezone: "UTC" },
          schedule_sync_status: "synced",
          last_fired_at: null,
          created_at: "2026-07-01T00:00:00Z",
          updated_at: "2026-07-01T00:00:00Z",
        },
      ],
      skill_bundles: [],
    } satisfies LoopSchemas.Loop;

    const values = loopToFormValues(loop);
    expect(values.triggers).toEqual([
      {
        key: "trigger-1",
        id: "trigger-1",
        type: "schedule",
        enabled: true,
        config: { cron_expression: "0 9 * * *", timezone: "UTC" },
      },
    ]);
    expect(values.contextTarget).toEqual({
      folderId: "f1",
      name: "growth",
      outputs: { post_to_feed: true, update_context: false, canvas_id: null },
    });
  });
});

describe("auto-fix behaviors", () => {
  it.each([
    { watch_ci: true, fix_review_comments: true, expected: true },
    { watch_ci: true, fix_review_comments: false, expected: false },
    { watch_ci: false, fix_review_comments: true, expected: false },
    { watch_ci: false, fix_review_comments: false, expected: false },
  ])(
    "reads on only when both flags are on (watch_ci=$watch_ci, fix=$fix_review_comments)",
    ({ watch_ci, fix_review_comments, expected }) => {
      expect(
        isAutoFixEnabled({
          ...defaultLoopBehaviors(),
          watch_ci,
          fix_review_comments,
        }),
      ).toBe(expected);
    },
  );
});
