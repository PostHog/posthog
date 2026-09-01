import type { AcpMessage, AgentSession } from "@posthog/shared";
import { afterEach, describe, expect, it } from "vitest";
import { sessionStore, sessionStoreSetters } from "./sessionStore";

const RUN = "run-evict";
const TASK = "task-evict";

function seedWithEvents() {
  sessionStoreSetters.setSession({
    taskRunId: RUN,
    taskId: TASK,
    events: [],
    messageQueue: [],
    pendingPermissions: new Map(),
    status: "disconnected",
  } as unknown as AgentSession);
  sessionStoreSetters.appendEvents(
    RUN,
    [{ ts: 1, message: {} } as unknown as AcpMessage],
    3,
  );
}

afterEach(() => sessionStoreSetters.removeSession(RUN));

describe("evictEvents / restoreEvents", () => {
  it("clears a starting marker when the session arrives", () => {
    sessionStoreSetters.setTaskStarting(TASK);

    sessionStoreSetters.setSession({
      taskRunId: RUN,
      taskId: TASK,
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
      status: "connected",
    } as unknown as AgentSession);

    expect(sessionStore.getState().startingTaskIds[TASK]).toBeUndefined();
  });

  it("evictEvents frees the transcript and resets the line cursor", () => {
    seedWithEvents();
    expect(sessionStore.getState().sessions[RUN].events).toHaveLength(1);

    sessionStoreSetters.evictEvents(RUN);

    const s = sessionStore.getState().sessions[RUN];
    expect(s.events).toHaveLength(0);
    expect(s.processedLineCount).toBe(0);
  });

  it("restoreEvents refills the transcript and freezes each event", () => {
    seedWithEvents();
    sessionStoreSetters.evictEvents(RUN);

    sessionStoreSetters.restoreEvents(
      RUN,
      [{ ts: 2, message: {} } as unknown as AcpMessage],
      7,
    );

    const s = sessionStore.getState().sessions[RUN];
    expect(s.events).toHaveLength(1);
    expect(s.processedLineCount).toBe(7);
    expect(Object.isFrozen(s.events[0])).toBe(true);
  });

  it.each([
    ["evictEvents", () => sessionStoreSetters.evictEvents(RUN)],
    [
      "restoreEvents",
      () =>
        sessionStoreSetters.restoreEvents(
          RUN,
          [{ ts: 2, message: {} } as unknown as AcpMessage],
          7,
        ),
    ],
  ])("%s retires the older-history paging index", (_name, transition) => {
    seedWithEvents();
    sessionStoreSetters.updateSession(RUN, { transcriptWindowStart: 10_000 });

    transition();

    expect(sessionStore.getState().sessions[RUN].transcriptWindowStart).toBe(0);
  });

  it("appendEvents and replaceOptimisticWithEvent freeze each stored event", () => {
    seedWithEvents();
    sessionStoreSetters.replaceOptimisticWithEvent(RUN, {
      ts: 2,
      message: {},
    } as unknown as AcpMessage);

    const s = sessionStore.getState().sessions[RUN];
    expect(s.events).toHaveLength(2);
    expect(s.events.every((event) => Object.isFrozen(event))).toBe(true);
  });

  it("evictEvents is a no-op on an already-empty session", () => {
    sessionStoreSetters.setSession({
      taskRunId: RUN,
      taskId: TASK,
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
      status: "disconnected",
    } as unknown as AgentSession);

    expect(() => sessionStoreSetters.evictEvents(RUN)).not.toThrow();
    expect(sessionStore.getState().sessions[RUN].events).toHaveLength(0);
  });
});
