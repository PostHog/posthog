import { ApiRequestError } from "@posthog/api-client/fetcher";
import { describe, expect, it, vi } from "vitest";
import { createBaseSession } from "./sessionFactory";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const TASK_ID = "task-1";
const TASK_RUN_ID = `run-${TASK_ID}`;

function createHarness(runError: unknown) {
  const session = {
    ...createBaseSession(TASK_RUN_ID, TASK_ID, "Test task"),
    status: "connected" as const,
    isCloud: true,
    cloudStatus: "completed" as const,
  };
  const invalidateQueries = vi.fn();
  const client = {
    getTaskRun: vi.fn().mockResolvedValue({
      id: TASK_RUN_ID,
      branch: "main",
      state: {},
      output: {},
    }),
    runTaskInCloud: vi.fn().mockRejectedValue(runError),
  };

  const deps = {
    store: {
      getSessionByTaskId: (taskId: string) =>
        taskId === session.taskId ? session : undefined,
      getSessions: () => ({ [TASK_RUN_ID]: session }),
      updateSession: (_taskRunId: string, updates: object) => {
        Object.assign(session, updates);
      },
      appendOptimisticItem: vi.fn(),
      clearTailOptimisticItems: vi.fn(),
      clearMessageQueue: vi.fn(),
    },
    h: {
      getCloudPromptTransport: (prompt: string) => ({
        promptText: prompt,
        messageText: prompt,
        filePaths: [],
        skillBundles: [],
      }),
      uploadTaskStagedAttachments: vi.fn().mockResolvedValue([]),
    },
    settings: { rtkEnabledCloud: false },
    queryClient: { invalidateQueries },
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    track: vi.fn(),
    getIsOnline: () => true,
    addDirectoryDialog: { open: false },
    fetchAuthState: async () => ({
      status: "authenticated",
      bootstrapComplete: true,
      cloudRegion: "us",
      currentProjectId: 2,
    }),
    createAuthenticatedClient: () => client,
    trpc: {
      agent: {
        onSessionIdleKilled: { subscribe: () => ({ unsubscribe: vi.fn() }) },
      },
    },
  } as unknown as SessionServiceDeps;

  return { service: new SessionService(deps), invalidateQueries, client };
}

describe("SessionService follow-up on a finished cloud run the server refuses to resume", () => {
  it.each([
    [
      "another run is in progress",
      "This task already has a run in progress. Wait for it to finish or cancel it first.",
    ],
    [
      "the task is done",
      "This task is done. Start a new task to keep working on it.",
    ],
  ])(
    "shows the server's reason and refetches the task when %s",
    async (_name, reason) => {
      const { service, invalidateQueries, client } = createHarness(
        new ApiRequestError(409, JSON.stringify({ error: reason }), {
          error: reason,
        }),
      );

      await expect(
        service.sendPrompt(TASK_ID, "keep going"),
      ).rejects.toMatchObject({ message: reason });

      expect(client.runTaskInCloud).toHaveBeenCalledTimes(1);
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["tasks"] });
    },
  );

  it("keeps the original error for a failure that is not a refusal", async () => {
    const { service, invalidateQueries } = createHarness(
      new ApiRequestError(502, "bad gateway"),
    );

    await expect(
      service.sendPrompt(TASK_ID, "keep going"),
    ).rejects.toMatchObject({ message: "Failed request: [502] bad gateway" });

    expect(invalidateQueries).not.toHaveBeenCalled();
  });
});
