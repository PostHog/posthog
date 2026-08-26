import { describe, expect, it, vi } from "vitest";
import { persistAgentFlowSessions } from "./flow-session-persistence";

function fakeSession(flushed: boolean) {
  const rewrite = vi.fn();
  const sessionManager = { flushed, _rewriteFile: rewrite };
  let handler: (event: unknown) => void = () => {};
  const session = {
    sessionManager,
    subscribe: (listener: (event: unknown) => void) => {
      handler = listener;
      return () => {};
    },
  };
  persistAgentFlowSessions(session as never);
  return {
    rewrite,
    sessionManager,
    emit: (event: unknown) => handler(event),
  };
}

function flowMessageEnd() {
  return {
    type: "message_end",
    message: {
      role: "custom",
      customType: "posthog-agent-flow",
      content: "step done",
      display: true,
      timestamp: 1,
    },
  };
}

describe("persistAgentFlowSessions", () => {
  it("flushes an unflushed session on the first flow message and marks it flushed", () => {
    const { rewrite, sessionManager, emit } = fakeSession(false);

    emit(flowMessageEnd());
    emit(flowMessageEnd());

    expect(rewrite).toHaveBeenCalledTimes(1);
    expect(sessionManager.flushed).toBe(true);
  });

  it("does not rewrite an already flushed session", () => {
    const { rewrite, emit } = fakeSession(true);
    emit(flowMessageEnd());
    expect(rewrite).not.toHaveBeenCalled();
  });

  it("ignores non-flow events", () => {
    const { rewrite, emit } = fakeSession(false);

    emit({ type: "agent_settled" });
    emit({
      type: "message_end",
      message: { role: "custom", customType: "other", content: "x" },
    });

    expect(rewrite).not.toHaveBeenCalled();
  });
});
