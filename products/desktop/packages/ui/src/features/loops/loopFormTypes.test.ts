import type { LoopSchemas } from "@posthog/api-client/loops";
import { systemTimezone } from "@posthog/ui/primitives/timezone";
import { describe, expect, it } from "vitest";
import {
  defaultLoopBehaviors,
  emptyLoopFormValues,
  formValuesToLoopWrite,
  isAutoFixEnabled,
  isLoopFormValid,
  isTriggerDraftValid,
  type LoopFormValues,
  type LoopTriggerDraft,
  loopToFormValues,
  normalizeLoopFormValues,
  withAutoFix,
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
      expected: false,
    },
    {
      name: "github without events",
      trigger: githubTrigger({ events: [] }),
      expected: false,
    },
    {
      name: "api trigger",
      trigger: {
        key: "k3",
        type: "api",
        enabled: true,
        config: {},
      } as LoopTriggerDraft,
      expected: true,
    },
  ])("$name → $expected", ({ trigger, expected }) => {
    expect(isTriggerDraftValid(trigger)).toBe(expected);
  });
});

describe("isLoopFormValid", () => {
  it("accepts a named form with instructions and no triggers", () => {
    expect(isLoopFormValid({ ...validFormValues(), triggers: [] })).toBe(true);
  });

  it.each([
    { name: "blank name", patch: { name: "   " } },
    { name: "blank instructions", patch: { instructions: "\n" } },
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

describe("formValuesToLoopWrite", () => {
  it("trims name, description and model", () => {
    const write = formValuesToLoopWrite({
      ...validFormValues(),
      name: "  Digest  ",
      description: " daily ",
      model: " claude-sonnet-5 ",
    });
    expect(write.name).toBe("Digest");
    expect(write.description).toBe("daily");
    expect(write.model).toBe("claude-sonnet-5");
  });

  it("maps a context target to snake_case and null when detached", () => {
    const attached = formValuesToLoopWrite({
      ...validFormValues(),
      contextTarget: {
        folderId: "f1",
        name: "growth",
        outputs: { post_to_feed: true, update_context: false, canvas_id: null },
      },
    });
    expect(attached.context_target).toEqual({
      folder_id: "f1",
      name: "growth",
      outputs: { post_to_feed: true, update_context: false, canvas_id: null },
    });
    expect(formValuesToLoopWrite(validFormValues()).context_target).toBeNull();
  });

  it("carries trigger ids through so the backend updates in place", () => {
    const write = formValuesToLoopWrite({
      ...validFormValues(),
      triggers: [
        { ...githubTrigger(), id: "trigger-1" },
        scheduleTrigger({ cron_expression: "0 9 * * *" }),
      ],
    });
    expect(write.triggers?.map((t) => t.id)).toEqual(["trigger-1", undefined]);
  });
});

function baseLoop(): LoopSchemas.Loop {
  return {
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
    repositories: [],
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
    skill_bundles: [],
  };
}

describe("loopToFormValues round trip", () => {
  it("maps a loop back into form values that write the same shape", () => {
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

    const write = formValuesToLoopWrite(values);
    expect(write.name).toBe(loop.name);
    expect(write.visibility).toBe(loop.visibility);
    expect(write.context_target).toEqual(loop.context_target);
    expect(write.triggers).toEqual([
      {
        id: "trigger-1",
        type: "schedule",
        enabled: true,
        config: { cron_expression: "0 9 * * *", timezone: "UTC" },
      },
    ]);
  });
});

describe("skill-driven loops", () => {
  it("derives instructions from the skill and context on write", () => {
    const write = formValuesToLoopWrite({
      ...validFormValues(),
      instructions: "stale free text",
      skill: {
        kind: "local",
        name: "weekly-report",
        source: "user",
        path: "/skills/weekly-report",
      },
      skillContext: "Focus on churn.",
    });
    expect(write.instructions).toBe("/weekly-report\n\nFocus on churn.");
  });

  it("derives a bare invocation when the context is empty", () => {
    const write = formValuesToLoopWrite({
      ...validFormValues(),
      skill: {
        kind: "local",
        name: "weekly-report",
        source: "user",
        path: "/skills/weekly-report",
      },
      skillContext: "  ",
    });
    expect(write.instructions).toBe("/weekly-report");
  });

  it.each([
    {
      name: "skill with no instructions",
      skill: true,
      instructions: "",
      expected: true,
    },
    {
      name: "no skill and no instructions",
      skill: false,
      instructions: "",
      expected: false,
    },
    {
      name: "no skill with instructions",
      skill: false,
      instructions: "Do it.",
      expected: true,
    },
  ])(
    "isLoopFormValid: $name → $expected",
    ({ skill, instructions, expected }) => {
      expect(
        isLoopFormValid({
          ...validFormValues(),
          instructions,
          skill: skill
            ? { kind: "local", name: "s", source: "user", path: "/s" }
            : null,
        }),
      ).toBe(expected);
    },
  );

  it("maps an attached bundle back into an attached skill draft with its context", () => {
    const bundle: LoopSchemas.LoopSkillBundle = {
      id: "b1",
      skill_name: "weekly-report",
      skill_source: "user",
      size: 10,
      content_sha256: "a".repeat(64),
      uploaded_at: "2026-07-01T00:00:00Z",
    };
    const loop = {
      ...baseLoop(),
      instructions: "/weekly-report\n\nFocus on churn.",
      skill_bundles: [bundle],
    };

    const values = loopToFormValues(loop);
    expect(values.skill).toEqual({
      kind: "attached",
      name: "weekly-report",
      source: "user",
    });
    expect(values.skillContext).toBe("Focus on churn.");
    expect(formValuesToLoopWrite(values).instructions).toBe(loop.instructions);
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

  it("withAutoFix sets both flags together and preserves the rest", () => {
    const behaviors = {
      ...defaultLoopBehaviors(),
      create_prs: false,
      max_fix_iterations: 5,
    };
    expect(withAutoFix(behaviors, true)).toEqual({
      create_prs: false,
      watch_ci: true,
      fix_review_comments: true,
      max_fix_iterations: 5,
    });
    expect(withAutoFix(behaviors, false).watch_ci).toBe(false);
  });
});
