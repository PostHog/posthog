import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../utils/logger.js", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

import type { WorkspaceConnection } from "@posthog/workspace-client/client";
import {
  WorkspaceServerEvent,
  WorkspaceServerService,
  WorkspaceServerStatus,
} from "./service";

const CONNECTION: WorkspaceConnection = {
  url: "http://127.0.0.1:9999",
  secret: "test-secret",
};

type Internals = {
  spawnChild: () => Promise<WorkspaceConnection>;
  connection: WorkspaceConnection | null;
};

function internals(service: WorkspaceServerService): Internals {
  return service as unknown as Internals;
}

function withHealthySpawn(service: WorkspaceServerService) {
  const spawn = vi.fn(async () => {
    // Defer like the real spawnChild, which only sets the connection after the
    // async health poll, so concurrent start() callers coalesce on pendingStart.
    await Promise.resolve();
    internals(service).connection = CONNECTION;
    return CONNECTION;
  });
  internals(service).spawnChild = spawn;
  return spawn;
}

function withFailingSpawn(service: WorkspaceServerService) {
  const spawn = vi.fn(async (): Promise<WorkspaceConnection> => {
    throw new Error("unhealthy");
  });
  internals(service).spawnChild = spawn;
  return spawn;
}

function trackStatuses(
  service: WorkspaceServerService,
): WorkspaceServerStatus[] {
  const statuses: WorkspaceServerStatus[] = [];
  service.on(WorkspaceServerEvent.StatusChanged, (event) => {
    statuses.push(event.status);
  });
  return statuses;
}

describe("WorkspaceServerService", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe("start", () => {
    it("transitions idle -> starting -> ready and exposes the connection", async () => {
      const service = new WorkspaceServerService();
      withHealthySpawn(service);
      const statuses = trackStatuses(service);

      const result = await service.start();

      expect(result).toEqual(CONNECTION);
      expect(service.getConnection()).toEqual(CONNECTION);
      expect(service.getStatus()).toBe(WorkspaceServerStatus.Ready);
      expect(statuses).toEqual([
        WorkspaceServerStatus.Starting,
        WorkspaceServerStatus.Ready,
      ]);
      expect(service.getStatusSnapshot()).toEqual({
        status: WorkspaceServerStatus.Ready,
        attempt: 0,
      });
    });

    it("coalesces concurrent callers and does not respawn once connected", async () => {
      const service = new WorkspaceServerService();
      const spawn = withHealthySpawn(service);

      const first = service.start();
      const second = service.start();
      expect(first).toBe(second);
      await first;

      await expect(service.start()).resolves.toEqual(CONNECTION);
      expect(spawn).toHaveBeenCalledTimes(1);
    });
  });

  describe("supervised restart", () => {
    it("backs off, caps the attempts, then settles in failed", async () => {
      vi.useFakeTimers();
      const service = new WorkspaceServerService();
      const spawn = withFailingSpawn(service);
      const statuses = trackStatuses(service);

      service.start().catch(() => {});
      await vi.runAllTimersAsync();

      expect(service.getStatus()).toBe(WorkspaceServerStatus.Failed);
      // initial attempt + MAX_RESTART_ATTEMPTS (5) supervised retries
      expect(spawn).toHaveBeenCalledTimes(6);
      expect(statuses[0]).toBe(WorkspaceServerStatus.Starting);
      expect(statuses).toContain(WorkspaceServerStatus.Retrying);
      expect(statuses[statuses.length - 1]).toBe(WorkspaceServerStatus.Failed);
    });

    it("restart() resets the attempt budget after a failure", async () => {
      vi.useFakeTimers();
      const service = new WorkspaceServerService();
      const spawn = withFailingSpawn(service);

      service.start().catch(() => {});
      await vi.runAllTimersAsync();
      expect(service.getStatus()).toBe(WorkspaceServerStatus.Failed);

      spawn.mockImplementation(async () => {
        internals(service).connection = CONNECTION;
        return CONNECTION;
      });
      const result = await service.restart();

      expect(result).toEqual(CONNECTION);
      expect(service.getStatus()).toBe(WorkspaceServerStatus.Ready);
      expect(service.getStatusSnapshot().attempt).toBe(0);
    });
  });

  describe("stop", () => {
    it("goes idle, clears the connection and suppresses restarts", async () => {
      const service = new WorkspaceServerService();
      withHealthySpawn(service);
      await service.start();

      service.stop();

      expect(service.getStatus()).toBe(WorkspaceServerStatus.Idle);
      expect(service.getConnection()).toBeNull();
    });
  });
});
