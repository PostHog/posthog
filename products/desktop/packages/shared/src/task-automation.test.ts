import { describe, expect, expectTypeOf, it } from "vitest";
import {
  type CreateTaskAutomationOptions,
  createTaskAutomationSchema,
  taskAutomationSchema,
  taskAutomationValidationErrorSchema,
  type UpdateTaskAutomationOptions,
  updateTaskAutomationSchema,
} from "./task-automation";

describe("task automation contracts", () => {
  it("normalizes optional automation response fields", () => {
    expect(
      taskAutomationSchema.parse({
        id: "automation-1",
        name: "Daily PRs",
        prompt: "Check PRs",
        repository: "posthog/posthog",
        cron_expression: "0 9 * * *",
        last_run_at: null,
        last_run_status: null,
        last_task_id: null,
        last_task_run_id: null,
        last_error: null,
        created_at: "2026-07-21T00:00:00Z",
        updated_at: "2026-07-21T00:00:00Z",
      }),
    ).toMatchObject({
      github_integration: null,
      timezone: null,
      template_id: null,
      enabled: true,
    });
  });

  it("keeps create fields required and update fields partial", () => {
    const create = createTaskAutomationSchema.parse({
      name: "Daily PRs",
      prompt: "Check PRs",
      repository: "posthog/posthog",
      cron_expression: "0 9 * * *",
      timezone: "Europe/London",
    });
    const update = updateTaskAutomationSchema.parse({ enabled: false });

    expect(create.timezone).toBe("Europe/London");
    expect(update).toEqual({ enabled: false });
    expectTypeOf(create).toEqualTypeOf<CreateTaskAutomationOptions>();
    expectTypeOf(update).toEqualTypeOf<UpdateTaskAutomationOptions>();
  });

  it("preserves backend validation field attribution", () => {
    expect(
      taskAutomationValidationErrorSchema.parse({
        type: "validation_error",
        detail: "Enter a valid cron expression.",
        attr: "cron_expression",
      }),
    ).toEqual({
      type: "validation_error",
      code: "invalid_input",
      detail: "Enter a valid cron expression.",
      attr: "cron_expression",
    });
  });
});
