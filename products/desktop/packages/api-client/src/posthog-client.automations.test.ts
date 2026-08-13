import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  PostHogAPIClient,
  TaskAutomationValidationError,
} from "./posthog-client";

const automationPayload = {
  id: "automation-1",
  name: "Daily PRs",
  prompt: "Check PRs",
  repository: "posthog/posthog",
  github_integration: 7,
  cron_expression: "0 9 * * *",
  timezone: "Europe/London",
  template_id: "llm-skill:daily-prs",
  enabled: true,
  last_run_at: null,
  last_run_status: null,
  last_task_id: null,
  last_task_run_id: null,
  last_error: null,
  created_at: "2026-07-21T00:00:00Z",
  updated_at: "2026-07-21T00:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("PostHogAPIClient task automations", () => {
  const fetch = vi.fn();
  const client = new PostHogAPIClient(
    "https://app.posthog.test",
    async () => "access-token",
    async () => "refreshed-token",
    42,
    { appVersion: "test", fetch },
  );

  beforeEach(() => {
    fetch.mockReset();
  });

  it("lists automations and normalizes optional response fields", async () => {
    const minimalPayload = {
      ...automationPayload,
      github_integration: undefined,
      timezone: undefined,
      template_id: undefined,
      enabled: undefined,
    };
    fetch.mockResolvedValueOnce(
      jsonResponse({
        count: 1,
        next: null,
        previous: null,
        results: [minimalPayload],
      }),
    );

    await expect(client.listTaskAutomations()).resolves.toEqual([
      expect.objectContaining({
        id: "automation-1",
        github_integration: null,
        timezone: null,
        template_id: null,
        enabled: true,
      }),
    ]);
    expect(fetch).toHaveBeenCalledWith(
      new URL(
        "https://app.posthog.test/api/projects/42/task_automations/?limit=500",
      ),
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("gets and creates automations through generated endpoints", async () => {
    fetch
      .mockResolvedValueOnce(jsonResponse(automationPayload))
      .mockResolvedValueOnce(jsonResponse(automationPayload, 201));

    await expect(client.getTaskAutomation("automation-1")).resolves.toEqual(
      automationPayload,
    );
    await expect(
      client.createTaskAutomation({
        name: "Daily PRs",
        prompt: "Check PRs",
        repository: "posthog/posthog",
        github_integration: 7,
        cron_expression: "0 9 * * *",
        timezone: "Europe/London",
        template_id: "llm-skill:daily-prs",
        enabled: true,
      }),
    ).resolves.toEqual(automationPayload);

    expect(fetch).toHaveBeenNthCalledWith(
      2,
      new URL("https://app.posthog.test/api/projects/42/task_automations/"),
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "Daily PRs",
          prompt: "Check PRs",
          repository: "posthog/posthog",
          github_integration: 7,
          cron_expression: "0 9 * * *",
          timezone: "Europe/London",
          template_id: "llm-skill:daily-prs",
          enabled: true,
        }),
      }),
    );
  });

  it("updates, deletes, and runs automations", async () => {
    fetch
      .mockResolvedValueOnce(
        jsonResponse({ ...automationPayload, enabled: false }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(jsonResponse(automationPayload));

    await expect(
      client.updateTaskAutomation("automation-1", { enabled: false }),
    ).resolves.toMatchObject({ enabled: false });
    await expect(
      client.deleteTaskAutomation("automation-1"),
    ).resolves.toBeUndefined();
    await expect(client.runTaskAutomation("automation-1")).resolves.toEqual(
      automationPayload,
    );

    expect(fetch).toHaveBeenNthCalledWith(
      1,
      new URL(
        "https://app.posthog.test/api/projects/42/task_automations/automation-1/",
      ),
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ enabled: false }),
      }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      3,
      new URL(
        "https://app.posthog.test/api/projects/42/task_automations/automation-1/run/",
      ),
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch.mock.calls[2]?.[1]?.body).toBeUndefined();
  });

  it("preserves validation detail, code, and field attribution", async () => {
    fetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          type: "validation_error",
          code: "invalid_input",
          detail: "Enter a valid cron expression.",
          attr: "cron_expression",
        }),
        {
          status: 400,
          statusText: "Bad Request",
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    const request = client.createTaskAutomation({
      name: "Daily PRs",
      prompt: "Check PRs",
      repository: "posthog/posthog",
      cron_expression: "not a cron",
      timezone: "Europe/London",
    });

    await expect(request).rejects.toBeInstanceOf(TaskAutomationValidationError);
    await expect(request).rejects.toMatchObject({
      status: 400,
      code: "invalid_input",
      attr: "cron_expression",
      message: "Enter a valid cron expression.",
    });
  });
});
