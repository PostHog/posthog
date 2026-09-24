import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { RootLogger } from "@posthog/di/logger";
import { describe, expect, it, vi } from "vitest";
import type { SystemMap } from "./schemas";
import {
  type SystemMapAgent,
  type SystemMapScope,
  SystemMapService,
  type SystemMapStorage,
} from "./systemMapService";

const map: SystemMap = {
  summary: "A parcel service.",
  coverage: [
    {
      path: "src",
      status: "reviewed",
      summary: "Read the service.",
      componentIds: ["orders"],
    },
  ],
  areas: [
    {
      id: "sales",
      name: "Sales",
      summary: "Accept orders.",
      components: [
        {
          id: "orders",
          name: "Orders",
          summary: "Store orders.",
          operations: [],
          evidence: [
            { path: "src/orders.ts", line: 1, note: "Order entry point." },
          ],
        },
      ],
    },
  ],
  relationships: [],
  limitations: [],
};
const scope: SystemMapScope = {
  apiHost: "https://example.com",
  projectId: 1,
  userId: "user-a",
  repoPath: "/parcel-service",
};
const logger: RootLogger = {
  debug: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  scope: () => logger,
};

function setup() {
  const values = new Map<string, string>();
  const storage: SystemMapStorage = {
    getItem: async (key) => values.get(key) ?? null,
    setItem: async (key, value) => {
      values.set(key, value);
    },
  };
  const agent: SystemMapAgent = {
    start: { mutate: vi.fn().mockResolvedValue(undefined) },
    prompt: { mutate: vi.fn().mockResolvedValue(undefined) },
    cancel: { mutate: vi.fn().mockResolvedValue(undefined) },
  };
  const getTaskRun = vi
    .fn()
    .mockResolvedValue({ status: "completed", output: map });
  const client = {
    createTask: vi
      .fn()
      .mockResolvedValue({ id: "10000000-0000-4000-8000-000000000001" }),
    createTaskRun: vi
      .fn()
      .mockResolvedValue({ id: "10000000-0000-4000-8000-000000000002" }),
    getTaskRun,
  } as unknown as PostHogAPIClient;
  const service = new SystemMapService(agent, logger, storage);
  return { values, storage, agent, getTaskRun, client, service };
}

describe("system map persistence", () => {
  it("restores a completed scan from a new service using only the saved reference", async () => {
    const { service, client, storage, values, agent } = setup();
    const result = await service.analyze(client, {
      ...scope,
      signal: new AbortController().signal,
    });
    expect(JSON.parse([...values.values()][0])).toEqual({
      taskId: result.taskId,
      runId: result.runId,
      analyzedAt: result.analyzedAt,
    });
    const restarted = new SystemMapService(agent, logger, storage);
    await expect(restarted.restore(client, scope)).resolves.toEqual(result);
    expect(agent.start.mutate).toHaveBeenCalledTimes(1);
  });

  it.each([
    { apiHost: "https://other.example.com" },
    { projectId: 2 },
    { userId: "user-b" },
    { repoPath: "/another-repo" },
  ])("does not restore another scope: %j", async (other) => {
    const { service, client, getTaskRun } = setup();
    await service.analyze(client, {
      ...scope,
      signal: new AbortController().signal,
    });
    getTaskRun.mockClear();
    await expect(
      service.restore(client, { ...scope, ...other }),
    ).resolves.toBeNull();
    expect(getTaskRun).not.toHaveBeenCalled();
  });

  it.each(["failed", "cancelled", "completed"])(
    "keeps the last successful reference after a %s run without a map",
    async (status) => {
      const { service, client, getTaskRun, values } = setup();
      const result = await service.analyze(client, {
        ...scope,
        signal: new AbortController().signal,
      });
      const saved = [...values.entries()];
      getTaskRun.mockResolvedValueOnce({ status, output: {} });
      await expect(
        service.analyze(client, {
          ...scope,
          signal: new AbortController().signal,
        }),
      ).rejects.toThrow();
      expect([...values.entries()]).toEqual(saved);
      await expect(service.restore(client, scope)).resolves.toEqual(result);
    },
  );

  it.each(["network", "invalid output"])(
    "keeps the reference when restore fails with %s so users can retry",
    async (failure) => {
      const { service, client, getTaskRun, values } = setup();
      const result = await service.analyze(client, {
        ...scope,
        signal: new AbortController().signal,
      });
      const saved = [...values.entries()];
      if (failure === "network")
        getTaskRun.mockRejectedValueOnce(new Error("Offline"));
      else getTaskRun.mockResolvedValueOnce({ output: {} });
      await expect(service.restore(client, scope)).rejects.toThrow();
      expect([...values.entries()]).toEqual(saved);
      await expect(service.restore(client, scope)).resolves.toEqual(result);
    },
  );

  it.each(["{", JSON.stringify({ taskId: "invalid" })])(
    "rejects an invalid stored reference before calling the API",
    async (invalid) => {
      const { service, client, values, getTaskRun } = setup();
      await service.analyze(client, {
        ...scope,
        signal: new AbortController().signal,
      });
      values.set([...values.keys()][0], invalid);
      getTaskRun.mockClear();
      await expect(service.restore(client, scope)).rejects.toThrow();
      expect(getTaskRun).not.toHaveBeenCalled();
    },
  );

  it.each(["throws", "silently fails"])(
    "returns the new map with a warning when storage %s",
    async (failure) => {
      const { service, client, storage } = setup();
      storage.setItem = async () => {
        if (failure === "throws") throw new Error("Disk full");
      };
      const result = await service.analyze(client, {
        ...scope,
        signal: new AbortController().signal,
      });
      expect(result.map).toEqual(map);
      expect(result.saveError).toContain("could not be saved");
    },
  );
});
