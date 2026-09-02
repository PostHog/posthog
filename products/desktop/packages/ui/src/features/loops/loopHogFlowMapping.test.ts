import type { Schemas } from "@posthog/api-client/generated";
import { describe, expect, it } from "vitest";
import {
  emptyLoopFormValues,
  type LoopFormValues,
  loopToFormValues,
} from "./loopFormTypes";
import {
  formValuesToHogFlowWrite,
  hogFlowTeamSkills,
  hogFlowToLoop,
  isLoopShapedHogFlow,
  type LoopHogFlowSource,
  taskToLoopRun,
  UnsupportedLoopShapeError,
} from "./loopHogFlowMapping";

const PROJECT_ID = 42;

function must<T>(value: T | null | undefined): T {
  if (value == null) throw new Error("expected a value");
  return value;
}

function scheduleValues(
  overrides: Partial<LoopFormValues> = {},
): LoopFormValues {
  return {
    ...emptyLoopFormValues(),
    name: "  Morning triage  ",
    description: "Look at overnight errors ",
    instructions: "Triage the error tracking inbox.\n",
    triggers: [
      {
        key: "t1",
        type: "schedule",
        enabled: true,
        config: { cron_expression: "0 9 * * 1-5", timezone: "Europe/Lisbon" },
      },
    ],
    ...overrides,
  };
}

function githubValues(overrides: Partial<LoopFormValues> = {}): LoopFormValues {
  return scheduleValues({
    triggers: [
      {
        key: "t1",
        type: "github",
        enabled: true,
        config: {
          github_integration_id: 7,
          repository: "example/app",
          events: ["pull_request"],
          filters: { actions: ["opened", "reopened"] },
        },
      },
    ],
    ...overrides,
  });
}

/** The flow the API would hand back after a write, so read mapping can be
 * checked against exactly what write mapping produced. */
function flowFromWrite(
  values: LoopFormValues,
  options: { enabled: boolean } = { enabled: true },
): LoopHogFlowSource {
  const { flow, schedule } = formValuesToHogFlowWrite(values, options);
  return {
    id: "flow-1",
    name: flow.name,
    description: flow.description,
    status: flow.status,
    created_at: "2026-09-01T08:00:00Z",
    updated_at: "2026-09-02T08:00:00Z",
    created_by: { id: 5 },
    actions: flow.actions,
    schedules: schedule
      ? [
          {
            id: "sched-1",
            ...schedule,
            status: "active",
            next_run_at: null,
            created_at: "2026-09-01T08:00:00Z",
            updated_at: "2026-09-01T08:00:00Z",
          } satisfies Schemas.HogFlowSchedule,
        ]
      : [],
  };
}

function taskAction(flow: LoopHogFlowSource): Record<string, unknown> {
  const actions = flow.actions as Array<Record<string, unknown>>;
  return must(actions.find((action) => action.type === "function"));
}

describe("loopHogFlowMapping", () => {
  it("writes a schedule loop as trigger, create-task step and exit plus a schedule row", () => {
    const { flow, schedule } = formValuesToHogFlowWrite(scheduleValues(), {
      enabled: true,
    });
    expect(flow).toMatchObject({
      name: "Morning triage",
      description: "Look at overnight errors",
      status: "active",
      origin_product: "loops",
      exit_condition: "exit_only_at_end",
    });
    expect(flow.actions.map((action) => [action.id, action.type])).toEqual([
      ["trigger", "trigger"],
      ["create_task", "function"],
      ["exit", "exit"],
    ]);
    expect(flow.actions[0].config).toEqual({ type: "schedule" });
    expect(flow.actions[1].config).toEqual({
      template_id: "template-posthog-create-task",
      inputs: { prompt: { value: "Triage the error tracking inbox." } },
    });
    expect(flow.edges).toEqual([
      { from: "trigger", to: "create_task", type: "continue" },
      { from: "create_task", to: "exit", type: "continue" },
    ]);
    expect(schedule).toMatchObject({
      rrule: "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=9;BYMINUTE=0;BYSECOND=0",
      timezone: "Europe/Lisbon",
    });
  });

  it("writes a paused loop as a draft", () => {
    expect(
      formValuesToHogFlowWrite(scheduleValues(), { enabled: false }).flow
        .status,
    ).toBe("draft");
  });

  it("writes a GitHub loop as an internal-event trigger with exact filters and no schedule", () => {
    const { flow, schedule } = formValuesToHogFlowWrite(githubValues(), {
      enabled: true,
    });
    expect(schedule).toBeNull();
    expect(flow.actions[0].config).toEqual({
      type: "internal-event",
      filters: {
        source: "internal-events",
        events: [{ id: "$github_event_received", type: "events" }],
        properties: [
          {
            key: "repository",
            value: ["example/app"],
            operator: "exact",
            type: "event",
          },
          {
            key: "event_type",
            value: ["pull_request"],
            operator: "exact",
            type: "event",
          },
          {
            key: "action",
            value: ["opened", "reopened"],
            operator: "exact",
            type: "event",
          },
        ],
      },
    });
  });

  it("only writes the task inputs the form filled in", () => {
    const { flow } = formValuesToHogFlowWrite(
      scheduleValues({
        repositories: [{ github_integration_id: 7, full_name: "example/app" }],
        model: "claude-opus-5",
        reasoningEffort: "high",
        teamSkills: ["error-triage", "db-runbook"],
      }),
      { enabled: true },
    );
    expect(flow.actions[1].config).toMatchObject({
      inputs: {
        prompt: { value: "Triage the error tracking inbox." },
        repository: { value: "example/app" },
        model: { value: { model: "claude-opus-5", reasoning_effort: "high" } },
        skills: { value: ["error-triage", "db-runbook"] },
      },
    });
  });

  it.each([
    [
      "an API trigger",
      scheduleValues({
        triggers: [{ key: "t1", type: "api", enabled: true, config: {} }],
      }),
    ],
    [
      "a cron outside the presets",
      scheduleValues({
        triggers: [
          {
            key: "t1",
            type: "schedule",
            enabled: true,
            config: { cron_expression: "*/15 * * * *" },
          },
        ],
      }),
    ],
    [
      "two enabled triggers",
      scheduleValues({
        triggers: [
          ...scheduleValues().triggers,
          ...githubValues().triggers.map((trigger) => ({
            ...trigger,
            key: "t2",
          })),
        ],
      }),
    ],
  ])("refuses to write %s", (_label, values) => {
    expect(() => formValuesToHogFlowWrite(values, { enabled: true })).toThrow(
      UnsupportedLoopShapeError,
    );
  });

  it.each([
    ["schedule", scheduleValues()],
    ["GitHub", githubValues()],
  ])(
    "reads a %s loop back into the form values that wrote it",
    (_label, values) => {
      const flow = flowFromWrite(values);
      expect(isLoopShapedHogFlow(flow)).toBe(true);
      const loop = hogFlowToLoop(flow, { projectId: PROJECT_ID });
      expect(loop).toMatchObject({
        id: "flow-1",
        team_id: PROJECT_ID,
        created_by_id: 5,
        name: "Morning triage",
        enabled: true,
        visibility: "team",
        origin_product: "loops",
      });
      const trigger = values.triggers[0];
      expect(loopToFormValues(loop)).toEqual({
        ...values,
        name: "Morning triage",
        description: "Look at overnight errors",
        instructions: "Triage the error tracking inbox.",
        visibility: "team",
        triggers: [
          {
            key: "trigger",
            id: "trigger",
            type: trigger.type,
            enabled: true,
            config:
              trigger.type === "github"
                ? { ...trigger.config, github_integration_id: 0 }
                : trigger.config,
          },
        ],
      });
    },
  );

  it("reads a draft flow as a paused loop with its model and repository", () => {
    const flow = flowFromWrite(
      scheduleValues({
        repositories: [{ github_integration_id: 7, full_name: "example/app" }],
        model: "claude-opus-5",
        reasoningEffort: "high",
        teamSkills: ["error-triage"],
      }),
      { enabled: false },
    );
    const loop = hogFlowToLoop(flow, { projectId: PROJECT_ID });
    expect(loop.enabled).toBe(false);
    expect(loop.model).toBe("claude-opus-5");
    expect(loop.reasoning_effort).toBe("high");
    expect(loop.repositories).toEqual([
      { github_integration_id: 0, full_name: "example/app" },
    ]);
    expect(hogFlowTeamSkills(flow)).toEqual(["error-triage"]);
  });

  it("treats a list row without schedules as loop-shaped with an empty cadence", () => {
    const { schedules: _omitted, ...row } = flowFromWrite(scheduleValues());
    expect(isLoopShapedHogFlow(row)).toBe(true);
    expect(
      hogFlowToLoop(row, { projectId: PROJECT_ID }).triggers[0].config,
    ).toEqual({});
  });

  it.each([
    [
      "an extra step in the graph",
      (flow: LoopHogFlowSource) => {
        (flow.actions as unknown[]).splice(1, 0, {
          id: "wait",
          name: "Wait",
          type: "delay",
          config: { delay_duration: "1h" },
        });
      },
    ],
    [
      "a different function template",
      (flow: LoopHogFlowSource) => {
        (taskAction(flow).config as Record<string, unknown>).template_id =
          "template-slack";
      },
    ],
    [
      "a schedule rule the form cannot express",
      (flow: LoopHogFlowSource) => {
        must(flow.schedules)[0].rrule =
          "FREQ=DAILY;INTERVAL=2;BYHOUR=9;BYMINUTE=0";
      },
    ],
  ])(
    "marks a schedule loop with %s as foreign but still maps its metadata",
    (_label, mutate) => {
      const flow = flowFromWrite(scheduleValues());
      mutate(flow);
      expect(isLoopShapedHogFlow(flow)).toBe(false);
      expect(hogFlowToLoop(flow, { projectId: PROJECT_ID })).toMatchObject({
        name: "Morning triage",
        enabled: true,
        triggers: [],
      });
    },
  );

  it.each([
    [
      "an actor filter added in the workflow editor",
      {
        key: "actor_access",
        value: ["write"],
        operator: "exact",
        type: "event",
      },
    ],
    [
      "a substring repository match",
      {
        key: "repository",
        value: "example",
        operator: "icontains",
        type: "event",
      },
    ],
    [
      "an event type loops do not offer",
      {
        key: "event_type",
        value: ["pull_request_review"],
        operator: "exact",
        type: "event",
      },
    ],
  ])("marks a GitHub loop with %s as foreign", (_label, property) => {
    const flow = flowFromWrite(githubValues());
    const trigger = (flow.actions as Array<Record<string, unknown>>)[0];
    const filters = (trigger.config as Record<string, unknown>).filters as {
      properties: Record<string, unknown>[];
    };
    filters.properties = [
      ...filters.properties.filter((existing) => existing.key !== property.key),
      property,
    ];
    expect(isLoopShapedHogFlow(flow)).toBe(false);
  });

  it.each([
    [
      "a running task",
      "in_progress",
      "cloud",
      { status: "in_progress", completed_at: null },
    ],
    [
      "a legacy started status",
      "started",
      "cloud",
      { status: "in_progress", completed_at: null },
    ],
    [
      "a finished task",
      "completed",
      "local",
      {
        status: "completed",
        environment: "local",
        completed_at: "2026-09-02T09:05:00Z",
      },
    ],
  ])("maps %s to a loop run", (_label, status, environment, expected) => {
    const task = {
      id: "task-1",
      created_at: "2026-09-02T09:00:00Z",
      latest_run: {
        id: "run-1",
        task: "task-1",
        status,
        environment,
        branch: "loop/run-1",
        error_message: null,
        output: null,
        created_at: "2026-09-02T09:00:30Z",
        updated_at: "2026-09-02T09:05:00Z",
      },
    } as unknown as Schemas.TaskDetailDTO;
    expect(taskToLoopRun(task)).toMatchObject({
      id: "run-1",
      task_id: "task-1",
      loop_trigger_id: null,
      environment: "cloud",
      branch: "loop/run-1",
      created_at: "2026-09-02T09:00:30Z",
      ...expected,
    });
  });

  it("lists a task with no run yet as not started", () => {
    const task = {
      id: "task-1",
      created_at: "2026-09-02T09:00:00Z",
      latest_run: null,
    } as unknown as Schemas.TaskDetailDTO;
    expect(taskToLoopRun(task)).toMatchObject({
      id: "task-1",
      task_id: "task-1",
      status: "not_started",
      created_at: "2026-09-02T09:00:00Z",
      completed_at: null,
    });
  });
});
