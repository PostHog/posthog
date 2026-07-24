import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockFetch } = vi.hoisted(() => ({
  mockFetch: vi.fn(),
}));

vi.mock("expo/fetch", () => ({
  fetch: mockFetch,
}));

vi.mock("@/lib/api", () => ({
  getBaseUrl: () => "https://app.posthog.test",
  getProjectId: () => 42,
  authedFetch: (url: string, init?: RequestInit) =>
    mockFetch(url, {
      ...init,
      headers: {
        Authorization: "Bearer token",
        "Content-Type": "application/json",
        ...((init?.headers as Record<string, string> | undefined) ?? {}),
      },
    }),
}));

import {
  createTaskAutomation,
  deleteTaskAutomation,
  getTaskAutomation,
  getTaskAutomations,
  runTaskAutomation,
  TaskAutomationValidationError,
  updateTaskAutomation,
} from "./api";

const automationPayload = {
  id: "automation-1",
  name: "Daily PRs",
  prompt: "Check PRs",
  repository: "posthog/posthog",
  github_integration: 7,
  cron_expression: "0 9 * * *",
  timezone: "Europe/London",
  template_id: "llm-skill:shared-daily-brief",
  enabled: true,
  last_run_at: null,
  last_run_status: null,
  last_task_id: "task-1",
  last_task_run_id: null,
  last_error: null,
  created_at: "2026-05-13T00:00:00Z",
  updated_at: "2026-05-13T00:00:00Z",
};

describe("task automation api", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("lists task automations from the existing backend endpoint", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          results: [automationPayload],
        }),
        { status: 200 },
      ),
    );

    const automations = await getTaskAutomations();

    expect(automations).toHaveLength(1);
    expect(automations[0]?.id).toBe("automation-1");
    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/projects/42/task_automations/?limit=500",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer token",
        }),
      }),
    );
  });

  it("serializes automation creation payloads with the existing backend contract", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify(automationPayload), { status: 200 }),
    );

    await createTaskAutomation({
      name: "Daily PRs",
      prompt: "Check PRs",
      repository: "posthog/posthog",
      github_integration: 7,
      cron_expression: "0 9 * * *",
      timezone: "Europe/London",
      enabled: true,
      template_id: "llm-skill:shared-daily-brief",
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/projects/42/task_automations/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "Daily PRs",
          prompt: "Check PRs",
          repository: "posthog/posthog",
          github_integration: 7,
          cron_expression: "0 9 * * *",
          timezone: "Europe/London",
          enabled: true,
          template_id: "llm-skill:shared-daily-brief",
        }),
      }),
    );
  });

  it("serializes skill-backed automation payloads with a prefixed template id", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ...automationPayload,
          id: "automation-2",
          name: "Shared daily brief",
          template_id: "llm-skill:shared-daily-brief",
        }),
        { status: 200 },
      ),
    );

    await createTaskAutomation({
      name: "Shared daily brief",
      prompt: "Summarize feature usage for my product areas.",
      repository: "posthog/posthog",
      github_integration: 7,
      cron_expression: "0 8 * * 1-5",
      timezone: "America/New_York",
      enabled: true,
      template_id: "llm-skill:shared-daily-brief",
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/projects/42/task_automations/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "Shared daily brief",
          prompt: "Summarize feature usage for my product areas.",
          repository: "posthog/posthog",
          github_integration: 7,
          cron_expression: "0 8 * * 1-5",
          timezone: "America/New_York",
          enabled: true,
          template_id: "llm-skill:shared-daily-brief",
        }),
      }),
    );
  });

  it("retains backend field attribution for validation errors", async () => {
    mockFetch.mockImplementation(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            type: "validation_error",
            code: "invalid_input",
            detail:
              "Only standard 5-field cron expressions are supported (minute hour day month weekday). Example: '0 9 * * 1-5'.",
            attr: "cron_expression",
          }),
          { status: 400, statusText: "Bad Request" },
        ),
      ),
    );

    await expect(
      createTaskAutomation({
        name: "Daily PRs",
        prompt: "Check PRs",
        repository: "posthog/posthog",
        cron_expression: "not a cron",
        timezone: "Europe/London",
      }),
    ).rejects.toBeInstanceOf(TaskAutomationValidationError);

    await expect(
      createTaskAutomation({
        name: "Daily PRs",
        prompt: "Check PRs",
        repository: "posthog/posthog",
        cron_expression: "not a cron",
        timezone: "Europe/London",
      }),
    ).rejects.toMatchObject({
      attr: "cron_expression",
      code: "invalid_input",
    });
  });

  it("surfaces skill-backed validation failures without losing backend attr info", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          type: "validation_error",
          code: "invalid_input",
          detail: "Repository is still required for this template.",
          attr: "repository",
        }),
        { status: 400, statusText: "Bad Request" },
      ),
    );

    await expect(
      createTaskAutomation({
        name: "Shared daily brief",
        prompt: "Summarize feature usage for my product areas.",
        repository: "",
        github_integration: null,
        cron_expression: "0 8 * * 1-5",
        timezone: "America/New_York",
        enabled: true,
        template_id: "llm-skill:shared-daily-brief",
      }),
    ).rejects.toMatchObject({
      attr: "repository",
      code: "invalid_input",
      message: "Repository is still required for this template.",
    });
  });

  it("supports retrieve, update, delete, and run-now automation flows", async () => {
    mockFetch
      .mockResolvedValueOnce(
        new Response(JSON.stringify(automationPayload), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(automationPayload), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(automationPayload), { status: 200 }),
      );

    const retrieved = await getTaskAutomation("automation-1");
    const updated = await updateTaskAutomation("automation-1", {
      enabled: false,
      cron_expression: "30 14 * * *",
    });
    await deleteTaskAutomation("automation-1");
    const ran = await runTaskAutomation("automation-1");

    expect(retrieved.id).toBe("automation-1");
    expect(updated.id).toBe("automation-1");
    expect(ran.id).toBe("automation-1");
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      "https://app.posthog.test/api/projects/42/task_automations/automation-1/",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          enabled: false,
          cron_expression: "30 14 * * *",
        }),
      }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      3,
      "https://app.posthog.test/api/projects/42/task_automations/automation-1/",
      expect.objectContaining({
        method: "DELETE",
      }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      4,
      "https://app.posthog.test/api/projects/42/task_automations/automation-1/run/",
      expect.objectContaining({
        method: "POST",
      }),
    );
  });
});
