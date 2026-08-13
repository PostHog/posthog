import type { AcpMessage, AgentSession } from "@posthog/shared";
import { afterEach, describe, expect, it } from "vitest";
import { sessionStoreSetters } from "../sessionStore";
import {
  type ConversationCacheKey,
  getConversationBuildCache,
  getPersistentThreadGrouper,
  MAX_CACHED_TASKS,
} from "./conversationDerivedCache";

function msg(ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: { jsonrpc: "2.0", method: "session/update", params: {} },
  };
}

const seededRuns: string[] = [];

function seedSession(
  taskId: string,
  taskRunId: string,
  events: AcpMessage[] = [msg(1)],
): void {
  sessionStoreSetters.setSession({
    taskId,
    taskRunId,
    events,
    messageQueue: [],
  } as unknown as AgentSession);
  seededRuns.push(taskRunId);
}

afterEach(() => {
  for (const taskRunId of seededRuns.splice(0)) {
    sessionStoreSetters.removeSession(taskRunId);
  }
});

describe("conversationDerivedCache", () => {
  it("returns the same cache entry across lookups for the same scope + task", () => {
    const key: ConversationCacheKey = {
      scope: "conversation-view",
      taskId: "same-entry",
    };
    expect(getConversationBuildCache(key)).toBe(getConversationBuildCache(key));
    expect(getPersistentThreadGrouper(key)).toBe(
      getPersistentThreadGrouper(key),
    );
  });

  it("keeps entries of different scopes for the same task independent", () => {
    const taskId = "scoped-entries";
    const a = getConversationBuildCache({ scope: "conversation-view", taskId });
    const b = getConversationBuildCache({ scope: "chat-thread", taskId });
    expect(a).not.toBe(b);
  });

  it("evicts the least recently used entry beyond the cap", () => {
    const first = getConversationBuildCache({
      scope: "chat-thread",
      taskId: "lru-0",
    });
    for (let i = 1; i <= MAX_CACHED_TASKS; i++) {
      getConversationBuildCache({ scope: "chat-thread", taskId: `lru-${i}` });
    }
    const recent = getConversationBuildCache({
      scope: "chat-thread",
      taskId: `lru-${MAX_CACHED_TASKS}`,
    });
    expect(
      getConversationBuildCache({
        scope: "chat-thread",
        taskId: `lru-${MAX_CACHED_TASKS}`,
      }),
    ).toBe(recent);
    expect(
      getConversationBuildCache({ scope: "chat-thread", taskId: "lru-0" }),
    ).not.toBe(first);
  });

  it("applies the LRU cap per scope, so one scope's fill doesn't shrink another's", () => {
    const first = getConversationBuildCache({
      scope: "conversation-view",
      taskId: "cap-0",
    });
    for (let i = 1; i < MAX_CACHED_TASKS; i++) {
      getConversationBuildCache({
        scope: "conversation-view",
        taskId: `cap-${i}`,
      });
    }
    for (let i = 0; i < MAX_CACHED_TASKS; i++) {
      getConversationBuildCache({ scope: "chat-thread", taskId: `cap-${i}` });
    }
    expect(
      getConversationBuildCache({
        scope: "conversation-view",
        taskId: "cap-0",
      }),
    ).toBe(first);
  });

  it("drops the cache when the session's events are evicted from the store", () => {
    const key: ConversationCacheKey = {
      scope: "conversation-view",
      taskId: "evicted-task",
    };
    seedSession(key.taskId, "run-evicted");
    const before = getConversationBuildCache(key);
    sessionStoreSetters.evictEvents("run-evicted");
    expect(getConversationBuildCache(key)).not.toBe(before);
  });

  it("drops the cache when the session is removed from the store", () => {
    const key: ConversationCacheKey = {
      scope: "conversation-view",
      taskId: "removed-task",
    };
    seedSession(key.taskId, "run-removed");
    const before = getConversationBuildCache(key);
    sessionStoreSetters.removeSession("run-removed");
    expect(getConversationBuildCache(key)).not.toBe(before);
  });

  it("drops the cache when the run it was built from is superseded by a re-run", () => {
    const key: ConversationCacheKey = {
      scope: "conversation-view",
      taskId: "rerun-task",
    };
    seedSession(key.taskId, "run-old");
    const before = getConversationBuildCache(key);
    // A re-run replaces the session under the same taskId; the entry was
    // built from the old run's events, so it must not survive on the back of
    // the new run's residency.
    seedSession(key.taskId, "run-new");
    expect(getConversationBuildCache(key)).not.toBe(before);
  });

  it("keeps entries for tasks that never had a session through store commits", () => {
    const key: ConversationCacheKey = {
      scope: "conversation-view",
      taskId: "sessionless-task",
    };
    const before = getConversationBuildCache(key);
    // An unrelated commit must not sweep surfaces rendering without a session
    // (e.g. archive views), or they would rebuild on every render.
    seedSession("unrelated-task", "run-unrelated");
    expect(getConversationBuildCache(key)).toBe(before);
  });

  it("does not tie an entry to a session whose events are not resident yet", () => {
    const key: ConversationCacheKey = {
      scope: "conversation-view",
      taskId: "empty-session-task",
    };
    seedSession(key.taskId, "run-empty", []);
    const before = getConversationBuildCache(key);
    // The sweep predicate is "no resident events"; latching on an empty
    // session would delete the entry on the very next commit.
    seedSession("other-task", "run-other");
    expect(getConversationBuildCache(key)).toBe(before);
  });
});
