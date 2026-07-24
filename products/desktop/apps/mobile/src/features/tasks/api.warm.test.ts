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

import { HttpError, warmTask } from "./api";

describe("warmTask", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("posts the warm request with the backend contract", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ task_id: "task-1", run_id: "run-1" }), {
        status: 200,
      }),
    );

    const result = await warmTask({
      repository: "posthog/posthog",
      github_integration: 7,
      branch: "main",
    });

    expect(result).toEqual({ task_id: "task-1", run_id: "run-1" });
    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/projects/42/tasks/warm/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          repository: "posthog/posthog",
          github_integration: 7,
          branch: "main",
          runtime_adapter: null,
          model: null,
          reasoning_effort: null,
        }),
      }),
    );
  });

  it("forwards the selected runtime, model, and reasoning effort", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ task_id: "task-1", run_id: "run-1" }), {
        status: 200,
      }),
    );

    await warmTask({
      repository: "posthog/posthog",
      github_integration: 7,
      branch: "main",
      runtime_adapter: "claude",
      model: "claude-opus-4-8",
      reasoning_effort: "high",
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/projects/42/tasks/warm/",
      expect.objectContaining({
        body: JSON.stringify({
          repository: "posthog/posthog",
          github_integration: 7,
          branch: "main",
          runtime_adapter: "claude",
          model: "claude-opus-4-8",
          reasoning_effort: "high",
        }),
      }),
    );
  });

  it("forwards the selected sandbox environment and custom image", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ task_id: "task-1", run_id: "run-1" }), {
        status: 200,
      }),
    );

    await warmTask({
      repository: "posthog/posthog",
      github_integration: 7,
      branch: "main",
      sandbox_environment_id: "environment-123",
      custom_image_id: "image-123",
    });

    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/projects/42/tasks/warm/",
      expect.objectContaining({
        body: JSON.stringify({
          repository: "posthog/posthog",
          github_integration: 7,
          branch: "main",
          runtime_adapter: null,
          model: null,
          reasoning_effort: null,
          sandbox_environment_id: "environment-123",
          custom_image_id: "image-123",
        }),
      }),
    );
  });

  it("omits the sandbox environment and custom image when unset", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ task_id: "task-1", run_id: "run-1" }), {
        status: 200,
      }),
    );

    await warmTask({
      repository: "posthog/posthog",
      github_integration: 7,
      sandbox_environment_id: null,
      custom_image_id: null,
    });

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body).not.toHaveProperty("sandbox_environment_id");
    expect(body).not.toHaveProperty("custom_image_id");
  });

  it("serializes a missing branch as null", async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ task_id: "task-1", run_id: "run-1" }), {
        status: 200,
      }),
    );

    await warmTask({ repository: "posthog/posthog", github_integration: 7 });

    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.test/api/projects/42/tasks/warm/",
      expect.objectContaining({
        body: JSON.stringify({
          repository: "posthog/posthog",
          github_integration: 7,
          branch: null,
          runtime_adapter: null,
          model: null,
          reasoning_effort: null,
        }),
      }),
    );
  });

  it("returns null when the response body is empty", async () => {
    mockFetch.mockResolvedValueOnce(new Response("", { status: 200 }));

    const result = await warmTask({
      repository: "posthog/posthog",
      github_integration: 7,
    });

    expect(result).toBeNull();
  });

  it("throws an HttpError on a failed response", async () => {
    mockFetch.mockResolvedValueOnce(new Response("nope", { status: 500 }));

    await expect(
      warmTask({ repository: "posthog/posthog", github_integration: 7 }),
    ).rejects.toBeInstanceOf(HttpError);
  });
});
