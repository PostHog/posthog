import type { WorkflowSchemas } from "@posthog/api-client/workflows";
import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  emptyHogFlowLoopFormValues,
  formValuesToHogFlowWrite,
  formValuesToScheduleWrite,
  hogFlowToFormValues,
  isDecompilableLoopHogFlow,
  isHogFlowLoopFormValid,
  taskToLoopRun,
} from "./loopHogFlowMapping";

const TRIGGER_ACTION: WorkflowSchemas.TriggerAction = {
  id: "trigger_node",
  name: "Schedule",
  type: "trigger",
  config: { type: "schedule" },
};

function taskAction(
  inputs: Partial<WorkflowSchemas.CreateTaskActionInputs> = {},
): WorkflowSchemas.CreateTaskAction {
  return {
    id: "create_ai_task",
    name: "Create AI task",
    type: "function",
    config: {
      template_id: "template-posthog-create-task",
      inputs: {
        prompt: { value: "Investigate failing CI runs" },
        non_failure_status_codes: { value: [409] },
        ...inputs,
      },
    },
    output_variable: { key: "task", result_path: null, label: "Task" },
  };
}

const LOOP_EDGE: WorkflowSchemas.HogFlowEdge = {
  from: "trigger_node",
  to: "create_ai_task",
  type: "continue",
};

function flow(
  overrides: Partial<WorkflowSchemas.HogFlow> = {},
): WorkflowSchemas.HogFlow {
  return {
    id: "flow-1",
    name: "My loop",
    description: "",
    version: 1,
    status: "active",
    created_at: "2026-01-01T00:00:00.000Z",
    created_by: { id: 1, email: "a@example.com" },
    updated_at: "2026-01-01T00:00:00.000Z",
    trigger: { type: "schedule" },
    edges: [LOOP_EDGE],
    actions: [TRIGGER_ACTION, taskAction()],
    abort_action: null,
    variables: null,
    schedules: [],
    user_access_level: "editor",
    ...overrides,
  };
}

const DAILY_SCHEDULE: WorkflowSchemas.HogFlowSchedule = {
  id: "sched-1",
  rrule: "FREQ=DAILY",
  starts_at: "2026-01-05T09:30:00.000Z",
  timezone: "UTC",
  variables: {},
  status: "active",
  next_run_at: "2026-01-06T09:30:00.000Z",
  created_at: "2026-01-01T00:00:00.000Z",
  updated_at: "2026-01-01T00:00:00.000Z",
};

describe("formValuesToHogFlowWrite", () => {
  it("builds a trigger + create-task action pair wired by one edge", () => {
    const values = {
      ...emptyHogFlowLoopFormValues(),
      name: "  My loop  ",
      instructions: "Do the thing",
    };

    const write = formValuesToHogFlowWrite(values, "active");

    expect(write.name).toBe("My loop");
    expect(write.status).toBe("active");
    expect(write.edges).toEqual([LOOP_EDGE]);
    expect(write.actions).toHaveLength(2);
    expect(write.actions[0]).toMatchObject({
      id: "trigger_node",
      type: "trigger",
      config: { type: "schedule" },
    });
    expect(write.actions[1]).toMatchObject({
      id: "create_ai_task",
      type: "function",
      config: {
        template_id: "template-posthog-create-task",
        inputs: { prompt: { value: "Do the thing" } },
      },
    });
  });

  it("omits optional create-task inputs the form left empty", () => {
    const write = formValuesToHogFlowWrite(
      emptyHogFlowLoopFormValues(),
      "draft",
    );
    const task = write.actions[1] as WorkflowSchemas.CreateTaskAction;
    expect(task.config.inputs.model).toBeUndefined();
    expect(task.config.inputs.repository).toBeUndefined();
    expect(task.config.inputs.skills).toBeUndefined();
  });

  it("includes model, repository, and skills when the form sets them", () => {
    const values = {
      ...emptyHogFlowLoopFormValues(),
      model: "claude-sonnet",
      reasoningEffort: "high" as const,
      repositories: [
        { github_integration_id: 1, full_name: "posthog/posthog" },
      ],
      skillNames: ["changelog-writer", "code-reviewer"],
    };

    const task = formValuesToHogFlowWrite(values, "active")
      .actions[1] as WorkflowSchemas.CreateTaskAction;

    expect(task.config.inputs.model).toEqual({
      value: { model: "claude-sonnet", reasoning_effort: "high" },
    });
    expect(task.config.inputs.repository).toEqual({ value: "posthog/posthog" });
    expect(task.config.inputs.skills).toEqual({
      value: ["changelog-writer", "code-reviewer"],
    });
  });
});

describe("formValuesToScheduleWrite", () => {
  it("compiles the form's single trigger into a schedule write", () => {
    const values = {
      ...emptyHogFlowLoopFormValues(),
      triggers: [
        {
          key: "k",
          type: "schedule" as const,
          enabled: true,
          config: { cron_expression: "0 * * * *", timezone: "UTC" },
        },
      ],
    };
    expect(formValuesToScheduleWrite(values)?.rrule).toBe("FREQ=HOURLY");
  });

  it("returns null with no triggers", () => {
    expect(
      formValuesToScheduleWrite({
        ...emptyHogFlowLoopFormValues(),
        triggers: [],
      }),
    ).toBeNull();
  });
});

describe("hogFlowToFormValues", () => {
  it("decompiles a loop-shaped flow's prompt, model, repository, and skills", () => {
    const values = hogFlowToFormValues(
      flow({
        actions: [
          TRIGGER_ACTION,
          taskAction({
            model: {
              value: { model: "claude-sonnet", reasoning_effort: "high" },
            },
            repository: { value: "posthog/posthog" },
            skills: { value: ["changelog-writer"] },
          }),
        ],
      }),
      DAILY_SCHEDULE,
    );

    expect(values.name).toBe("My loop");
    expect(values.instructions).toBe("Investigate failing CI runs");
    expect(values.model).toBe("claude-sonnet");
    expect(values.reasoningEffort).toBe("high");
    expect(values.repositories).toEqual([
      { github_integration_id: 0, full_name: "posthog/posthog" },
    ]);
    expect(values.skillNames).toEqual(["changelog-writer"]);
    expect(values.triggers[0].enabled).toBe(true);
    expect(values.triggers[0].config).toEqual({
      cron_expression: "30 9 * * *",
      timezone: "UTC",
    });
  });

  it("marks the trigger disabled for a non-active flow", () => {
    const values = hogFlowToFormValues(
      flow({ status: "draft" }),
      DAILY_SCHEDULE,
    );
    expect(values.triggers[0].enabled).toBe(false);
  });
});

describe("isDecompilableLoopHogFlow", () => {
  it("is true for a canonical loop shape with a recognized schedule", () => {
    expect(isDecompilableLoopHogFlow(flow(), DAILY_SCHEDULE)).toBe(true);
  });

  it("is false with no schedule", () => {
    expect(isDecompilableLoopHogFlow(flow(), null)).toBe(false);
  });

  it("is false for an rrule this feature didn't author", () => {
    expect(
      isDecompilableLoopHogFlow(flow(), {
        ...DAILY_SCHEDULE,
        rrule: "FREQ=MONTHLY;BYMONTHDAY=1",
      }),
    ).toBe(false);
  });

  it("is false for a flow with an extra action (hand-edited elsewhere)", () => {
    const extraAction: WorkflowSchemas.OtherAction = {
      id: "extra",
      name: "Extra",
      type: "function",
      config: {},
    };
    expect(
      isDecompilableLoopHogFlow(
        flow({ actions: [TRIGGER_ACTION, taskAction(), extraAction] }),
        DAILY_SCHEDULE,
      ),
    ).toBe(false);
  });
});

describe("isHogFlowLoopFormValid", () => {
  it("requires a name and instructions", () => {
    expect(isHogFlowLoopFormValid(emptyHogFlowLoopFormValues())).toBe(false);
    expect(
      isHogFlowLoopFormValid({
        ...emptyHogFlowLoopFormValues(),
        name: "x",
        instructions: "y",
      }),
    ).toBe(true);
  });

  it("is invalid when the trigger's cron doesn't compile to an rrule", () => {
    const values = {
      ...emptyHogFlowLoopFormValues(),
      name: "x",
      instructions: "y",
      triggers: [
        {
          key: "k",
          type: "schedule" as const,
          enabled: true,
          config: { cron_expression: "*/15 * * * *" },
        },
      ],
    };
    expect(isHogFlowLoopFormValid(values)).toBe(false);
  });
});

describe("taskToLoopRun", () => {
  it("adapts a task's latest run onto the LoopRun shape LoopRunRow renders", () => {
    const task: Task = {
      id: "task-1",
      task_number: 1,
      slug: "task-1",
      title: "Investigate",
      description: "",
      created_at: "2026-01-01T00:00:00.000Z",
      updated_at: "2026-01-01T00:00:00.000Z",
      origin_product: "workflow",
      latest_run: {
        id: "run-1",
        task: "task-1",
        team: 1,
        branch: "loop/task-1",
        environment: "cloud",
        status: "completed",
        log_url: "",
        error_message: null,
        output: null,
        state: {} as never,
        created_at: "2026-01-01T00:01:00.000Z",
        updated_at: "2026-01-01T00:02:00.000Z",
        completed_at: "2026-01-01T00:02:00.000Z",
      },
    };

    expect(taskToLoopRun(task)).toEqual({
      id: "run-1",
      task_id: "task-1",
      loop_trigger_id: null,
      status: "completed",
      environment: "cloud",
      branch: "loop/task-1",
      error_message: null,
      output: null,
      created_at: "2026-01-01T00:01:00.000Z",
      completed_at: "2026-01-01T00:02:00.000Z",
    });
  });

  it("returns null for a task with no run yet", () => {
    expect(
      taskToLoopRun({
        id: "task-1",
        task_number: 1,
        slug: "task-1",
        title: "Investigate",
        description: "",
        created_at: "2026-01-01T00:00:00.000Z",
        updated_at: "2026-01-01T00:00:00.000Z",
        origin_product: "workflow",
      }),
    ).toBeNull();
  });
});
