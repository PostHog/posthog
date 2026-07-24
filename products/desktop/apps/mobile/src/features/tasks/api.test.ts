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
  getAccessToken: () => "token",
  createTimeoutSignal: () => undefined,
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
  cancelRun,
  HttpError,
  presignTaskRunArtifact,
  runTaskInCloud,
} from "./api";

function bodyOf(call: unknown): Record<string, unknown> {
  const [, init] = call as [string, RequestInit];
  return JSON.parse(init.body as string);
}

describe("runTaskInCloud", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ id: "task-1" }), { status: 200 }),
    );
  });

  it.each([true, false])(
    "forwards auto_publish=%s to the payload",
    async (flag) => {
      await runTaskInCloud("task-1", { autoPublish: flag });

      expect(bodyOf(mockFetch.mock.calls[0])).toMatchObject({
        auto_publish: flag,
      });
    },
  );

  it("omits auto_publish when not provided", async () => {
    await runTaskInCloud("task-1", { model: "claude-opus-4-8" });

    expect(bodyOf(mockFetch.mock.calls[0])).not.toHaveProperty("auto_publish");
  });

  it("sends no body for the plain initial run", async () => {
    await runTaskInCloud("task-1");

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
  });

  it("forwards the selected sandbox environment and custom image", async () => {
    await runTaskInCloud("task-1", {
      sandboxEnvironmentId: "environment-123",
      customImageId: "image-123",
    });

    expect(bodyOf(mockFetch.mock.calls[0])).toMatchObject({
      sandbox_environment_id: "environment-123",
      custom_image_id: "image-123",
    });
  });

  it("omits the sandbox environment and custom image when unset", async () => {
    await runTaskInCloud("task-1", {
      model: "claude-opus-4-8",
      sandboxEnvironmentId: null,
      customImageId: null,
    });

    const body = bodyOf(mockFetch.mock.calls[0]);
    expect(body).not.toHaveProperty("sandbox_environment_id");
    expect(body).not.toHaveProperty("custom_image_id");
  });

  it("sends rtk_enabled=false when the run opts out", async () => {
    await runTaskInCloud("task-1", { rtkEnabled: false });

    expect(bodyOf(mockFetch.mock.calls[0])).toMatchObject({
      rtk_enabled: false,
    });
  });

  it("omits rtk_enabled when the run keeps compression on", async () => {
    await runTaskInCloud("task-1", { rtkEnabled: true });

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeUndefined();
  });
});

describe("cancelRun", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("POSTs to the run cancel endpoint with an empty body", async () => {
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ status: "cancelled" }), { status: 200 }),
    );

    const result = await cancelRun("task-1", "run-1");

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://app.posthog.test/api/projects/42/tasks/task-1/runs/run-1/cancel/",
    );
    expect(init.method).toBe("POST");
    expect(bodyOf(mockFetch.mock.calls[0])).toEqual({});
    expect(result).toEqual({ status: "cancelled" });
  });

  it("forwards a reason when provided", async () => {
    mockFetch.mockResolvedValue(new Response("{}", { status: 200 }));

    await cancelRun("task-1", "run-1", "user requested");

    expect(bodyOf(mockFetch.mock.calls[0])).toEqual({
      reason: "user requested",
    });
  });

  it("throws with the backend error message on failure", async () => {
    mockFetch.mockResolvedValue(
      new Response(JSON.stringify({ error: "Run already finished" }), {
        status: 409,
      }),
    );

    await expect(cancelRun("task-1", "run-1")).rejects.toMatchObject({
      status: 409,
      message: expect.stringContaining("Run already finished"),
    });
  });

  it("falls back to a generic message when the body has no error", async () => {
    mockFetch.mockResolvedValue(new Response("boom", { status: 500 }));

    await expect(cancelRun("task-1", "run-1")).rejects.toBeInstanceOf(
      HttpError,
    );
  });
});

describe("presignTaskRunArtifact", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("posts the storage path and returns the presigned URL", async () => {
    mockFetch.mockResolvedValue(
      new Response(
        JSON.stringify({ url: "https://s3.example.com/x.png?sig=abc" }),
        { status: 200 },
      ),
    );

    await expect(
      presignTaskRunArtifact("task-1", "run-1", "tasks/run-1/artifacts/x.png"),
    ).resolves.toBe("https://s3.example.com/x.png?sig=abc");

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://app.posthog.test/api/projects/42/tasks/task-1/runs/run-1/artifacts/presign/",
    );
    expect(init.method).toBe("POST");
    expect(bodyOf(mockFetch.mock.calls[0])).toEqual({
      storage_path: "tasks/run-1/artifacts/x.png",
    });
  });

  it("throws an HttpError on a non-OK response", async () => {
    mockFetch.mockResolvedValue(new Response("nope", { status: 500 }));

    await expect(
      presignTaskRunArtifact("task-1", "run-1", "tasks/run-1/artifacts/x.png"),
    ).rejects.toBeInstanceOf(HttpError);
  });
});
