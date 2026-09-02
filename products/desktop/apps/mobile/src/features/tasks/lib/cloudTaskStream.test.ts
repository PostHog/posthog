import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  engine: {
    off: vi.fn(),
    on: vi.fn(),
    reconnectIfDisconnected: vi.fn(),
    unwatch: vi.fn(),
    watch: vi.fn(),
  },
}));

vi.mock("@posthog/core/cloud-task/cloud-task-engine", () => ({
  createCloudTaskEngine: () => mocks.engine,
}));

vi.mock("@posthog/core/cloud-task/schemas", () => ({
  CloudTaskEvent: { Update: "cloud-task-update" },
}));

vi.mock("expo/fetch", () => ({ fetch: vi.fn() }));

vi.mock("@/lib/api", () => ({
  authedFetch: vi.fn(),
  getBaseUrl: () => "https://app.posthog.test",
  getProjectId: () => 42,
}));

vi.mock("@/lib/logger", () => ({
  logger: { scope: vi.fn() },
}));

import { watchCloudTask } from "./cloudTaskStream";

describe("watchCloudTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("asks the shared engine to reconnect only when disconnected", () => {
    const handle = watchCloudTask({
      taskId: "task-1",
      runId: "run-1",
      onUpdate: vi.fn(),
    });

    handle.reconnectIfDisconnected();

    expect(mocks.engine.reconnectIfDisconnected).toHaveBeenCalledWith(
      "task-1",
      "run-1",
    );
  });
});
