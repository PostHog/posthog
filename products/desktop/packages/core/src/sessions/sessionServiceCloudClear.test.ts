import {
  IMPORTED_USER_PROMPT_META_KEY,
  type StoredLogEntry,
} from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { POSTHOG_NOTIFICATIONS } from "./acpNotifications";
import {
  convertStoredEntriesToEvents,
  createConversationClearedEvents,
} from "./sessionEvents";
import { createBaseSession } from "./sessionFactory";
import {
  reconcileLiveEventsWithHydratedEvents,
  SessionService,
  type SessionServiceDeps,
} from "./sessionService";

const TASK_ID = "task-1";
const TASK_RUN_ID = `run-${TASK_ID}`;
const CLEAR_LOGGED_AT = "2026-08-14T10:00:00.000Z";

// The run's log as it stood before the clear boundary was appended.
const preClearLogEntries: StoredLogEntry[] = [
  {
    type: "notification",
    timestamp: "2026-08-14T09:59:00.000Z",
    notification: {
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text: "done" },
        },
      },
    },
  },
];

// The pair the backend persists into the run log on clear_conversation.
const clearedLogEntries: StoredLogEntry[] = [
  {
    type: "notification",
    timestamp: CLEAR_LOGGED_AT,
    notification: {
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "user_message_chunk",
          content: { type: "text", text: "/clear" },
          _meta: { [IMPORTED_USER_PROMPT_META_KEY]: true },
        },
      },
    },
  },
  {
    type: "notification",
    timestamp: "2026-08-14T10:00:00.001Z",
    notification: {
      method: POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED,
      params: {},
    },
  },
];

function createHarness({
  conversationClear = true,
  logEntries = clearedLogEntries,
}: {
  conversationClear?: boolean;
  logEntries?: StoredLogEntry[];
} = {}) {
  const session = {
    ...createBaseSession(TASK_RUN_ID, TASK_ID, "Test task"),
    status: "connected" as const,
    isCloud: true,
    cloudStatus: "completed" as const,
    conversationClear,
  };

  const appendEvents = vi.fn();
  const clearTaskRunConversation = vi.fn().mockResolvedValue(undefined);
  const runTaskInCloud = vi.fn();
  const getTaskRunSessionLogsResult = vi
    .fn()
    .mockResolvedValue({ entries: logEntries, complete: true });
  // The chain-window probe always reports more-than-a-page with an unknown
  // count, forcing hydration onto the getTaskRunSessionLogsResult path this
  // harness actually stubs.
  const getTaskRunSessionLogsPage = vi
    .fn()
    .mockResolvedValue({ entries: [], hasMore: true, matchingCount: null });

  const deps = {
    store: {
      getSessionByTaskId: (taskId: string) =>
        taskId === session.taskId ? session : undefined,
      getSessions: () => ({ [TASK_RUN_ID]: session }),
      updateSession: (_taskRunId: string, updates: object) => {
        Object.assign(session, updates);
      },
      appendEvents,
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
    },
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    getIsOnline: () => true,
    addDirectoryDialog: { open: false },
    getAuthenticatedClient: async () => ({
      clearTaskRunConversation,
      runTaskInCloud,
    }),
    fetchAuthState: async () => ({
      status: "authenticated",
      bootstrapComplete: true,
      cloudRegion: "us",
      currentProjectId: 2,
    }),
    createAuthenticatedClient: () => ({
      getTaskRunSessionLogsResult,
      getTaskRunSessionLogsPage,
    }),
    trpc: {
      agent: {
        onSessionIdleKilled: { subscribe: () => ({ unsubscribe: vi.fn() }) },
      },
    },
  } as unknown as SessionServiceDeps;

  return {
    service: new SessionService(deps),
    session,
    appendEvents,
    clearTaskRunConversation,
    runTaskInCloud,
    getTaskRunSessionLogsResult,
  };
}

describe("SessionService /clear on a finished cloud run", () => {
  it("records the boundary and repaints the thread from the persisted log", async () => {
    const {
      service,
      session,
      appendEvents,
      clearTaskRunConversation,
      runTaskInCloud,
      getTaskRunSessionLogsResult,
    } = createHarness();

    const result = await service.sendPrompt(TASK_ID, "/clear");

    expect(result).toEqual({ stopReason: "end_turn" });
    expect(clearTaskRunConversation).toHaveBeenCalledWith(TASK_ID, TASK_RUN_ID);
    expect(runTaskInCloud).not.toHaveBeenCalled();
    expect(getTaskRunSessionLogsResult).toHaveBeenCalledWith(
      TASK_ID,
      TASK_RUN_ID,
      { limit: 100000 },
    );

    // A finished run streams nothing back, so the thread is painted from here.
    // The user message must be a session/prompt request: the renderer drops raw
    // user_message_chunks, so painting one would show only the divider.
    expect(
      session.events.map((e) => (e.message as { method: string }).method),
    ).toEqual(["session/prompt", POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED]);
    const prompt = session.events[0].message as {
      params: { prompt: Array<{ text: string }> };
    };
    expect(prompt.params.prompt[0].text).toBe("/clear");

    // The frames must come from the log, carrying the backend's timestamp.
    // A locally stamped copy never reconciles against the persisted pair and
    // renders the /clear twice after the run is resumed.
    expect(session.events[0].ts).toBe(new Date(CLEAR_LOGGED_AT).getTime());
    expect(getTaskRunSessionLogsResult).toHaveBeenCalledTimes(1);
    expect(appendEvents).not.toHaveBeenCalled();
  });

  it("short-circuits a repeat /clear without another backend call", async () => {
    const {
      service,
      session,
      appendEvents,
      clearTaskRunConversation,
      getTaskRunSessionLogsResult,
    } = createHarness();

    await service.sendPrompt(TASK_ID, "/clear");
    await service.sendPrompt(TASK_ID, "/clear");

    expect(session.events).toHaveLength(2);
    expect(clearTaskRunConversation).toHaveBeenCalledTimes(1);
    expect(getTaskRunSessionLogsResult).toHaveBeenCalledTimes(1);
    expect(appendEvents).not.toHaveBeenCalled();
  });

  it("retries the repaint when the log read lags the boundary append", async () => {
    vi.useFakeTimers();
    try {
      const { service, session, appendEvents, getTaskRunSessionLogsResult } =
        createHarness();
      // An S3-backed read right after the POST can return the pre-append log
      // and still look complete.
      getTaskRunSessionLogsResult
        .mockResolvedValueOnce({ entries: preClearLogEntries, complete: true })
        .mockResolvedValue({
          entries: [...preClearLogEntries, ...clearedLogEntries],
          complete: true,
        });

      const promptPromise = service.sendPrompt(TASK_ID, "/clear");
      await vi.advanceTimersByTimeAsync(2_000);
      const result = await promptPromise;

      expect(result).toEqual({ stopReason: "end_turn" });
      expect(getTaskRunSessionLogsResult).toHaveBeenCalledTimes(2);
      expect(appendEvents).not.toHaveBeenCalled();
      expect(session.events).toHaveLength(3);
      expect(
        (session.events.at(-1)?.message as { method: string }).method,
      ).toBe(POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED);
    } finally {
      vi.useRealTimers();
    }
  });

  it("falls back to locally painted frames when the log never shows the boundary", async () => {
    vi.useFakeTimers();
    try {
      const { service, appendEvents, getTaskRunSessionLogsResult } =
        createHarness();
      getTaskRunSessionLogsResult.mockResolvedValue({
        entries: [],
        complete: false,
      });

      const promptPromise = service.sendPrompt(TASK_ID, "/clear");
      await vi.advanceTimersByTimeAsync(2_000);
      const result = await promptPromise;

      expect(result).toEqual({ stopReason: "end_turn" });
      expect(getTaskRunSessionLogsResult).toHaveBeenCalledTimes(3);
      const [, events] = appendEvents.mock.calls[0];
      expect(
        events.map((e: { message: { method: string } }) => e.message.method),
      ).toEqual(["session/prompt", POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED]);
      expect(events[0].message.params.prompt[0].text).toBe("/clear");
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not paint a boundary when the backend rejects the clear", async () => {
    const { service, session, appendEvents, clearTaskRunConversation } =
      createHarness();
    clearTaskRunConversation.mockRejectedValue(
      new Error("Couldn’t clear the conversation."),
    );

    await expect(service.sendPrompt(TASK_ID, "/clear")).rejects.toThrow(
      "Couldn’t clear the conversation.",
    );
    expect(session.events).toHaveLength(0);
    expect(appendEvents).not.toHaveBeenCalled();
  });

  // An older agent ignores the marker and resumes the conversation it was meant to
  // retire, so recording a boundary would claim a clear that never happens. Both
  // cases fall through to the ordinary resume, which this harness does not fake.
  it.each([
    [
      "the agent cannot honour the boundary",
      { conversationClear: false },
      "/clear",
    ],
    ["the message is not a /clear", {}, "keep going"],
  ])("does not record a boundary when %s", async (_case, options, prompt) => {
    const { service, clearTaskRunConversation } = createHarness(options);

    await service.sendPrompt(TASK_ID, prompt).catch(() => undefined);

    expect(clearTaskRunConversation).not.toHaveBeenCalled();
  });

  // The cleared run's events are copied into the resumed run's session, then
  // resume hydration promotes the same pair from the ancestor log. The two
  // conversions carry different position provenance, so reconciliation must
  // fall back to message equality and fold them into one copy.
  it("reconciles the log-derived clear pair on resume instead of duplicating it", () => {
    const paintedOnClearedRun = convertStoredEntriesToEvents(
      clearedLogEntries,
      undefined,
      // Any nonzero ordinal works: this copy is positioned while the resume
      // copy below is not, which is what forces the message-equality fallback.
      { taskRunId: TASK_RUN_ID, startEntryIndex: 6 },
    );
    const hydratedForResumedRun = convertStoredEntriesToEvents(
      clearedLogEntries,
      undefined,
      {
        taskRunId: "run-resumed",
        startEntryIndex: 0,
        firstPositionedEntryIndex: clearedLogEntries.length,
      },
    );

    const inherited = reconcileLiveEventsWithHydratedEvents(
      paintedOnClearedRun,
      hydratedForResumedRun,
    );

    expect(inherited).toEqual([]);

    // The fold above depends on the log copy carrying the backend's timestamp
    // as the prompt id. The locally stamped fallback never matches, which is
    // why clearCloudConversation repaints from the log instead of fabricating.
    const fabricatedFallback = createConversationClearedEvents(Date.now());
    const duplicated = reconcileLiveEventsWithHydratedEvents(
      fabricatedFallback,
      hydratedForResumedRun,
    );
    expect(
      duplicated.map((e) => (e.message as { method: string }).method),
    ).toEqual(["session/prompt", POSTHOG_NOTIFICATIONS.CONVERSATION_CLEARED]);
  });
});
