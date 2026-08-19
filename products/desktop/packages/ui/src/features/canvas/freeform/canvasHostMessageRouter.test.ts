import { describe, expect, it, vi } from "vitest";
import { createCanvasHostMessageRouter } from "./canvasHostMessageRouter";

describe("createCanvasHostMessageRouter", () => {
  it.each([
    [false, false],
    [true, true],
  ])(
    "forwards action invocations only under a user gesture (activation: %s)",
    async (hasActivation, forwarded) => {
      const post = vi.fn();
      const onDataRequest = vi.fn().mockResolvedValue({ ok: true });
      const route = createCanvasHostMessageRouter({
        post,
        callbacks: () => ({ onDataRequest }),
        hasUserActivation: () => hasActivation,
        openExternal: vi.fn(),
      });

      await route({
        channel: "posthog-canvas",
        type: "data-request",
        id: "request-1",
        method: "actionInvoke",
        payload: { verb: "tasks.create", payload: { title: "t" } },
      });

      if (forwarded) {
        expect(onDataRequest).toHaveBeenCalledWith("actionInvoke", {
          verb: "tasks.create",
          payload: { title: "t" },
        });
      } else {
        expect(onDataRequest).not.toHaveBeenCalled();
        expect(post).toHaveBeenCalledWith(
          expect.objectContaining({
            id: "request-1",
            ok: false,
            error: "Canvas actions require a user action",
          }),
        );
      }
    },
  );

  it("does not gate state reads or writes on a user gesture", async () => {
    const post = vi.fn();
    const onDataRequest = vi.fn().mockResolvedValue(null);
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({ onDataRequest }),
      hasUserActivation: () => false,
      openExternal: vi.fn(),
    });

    await route({
      channel: "posthog-canvas",
      type: "data-request",
      id: "request-2",
      method: "stateSet",
      payload: { scope: "user", key: "k", value: 1 },
    });

    expect(onDataRequest).toHaveBeenCalledWith("stateSet", {
      scope: "user",
      key: "k",
      value: 1,
    });
  });

  it("rejects agent requests that are not triggered by a user action", async () => {
    const post = vi.fn();
    const onDataRequest = vi.fn();
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({ onDataRequest }),
      hasUserActivation: () => false,
      openExternal: vi.fn(),
    });

    await route({
      channel: "posthog-canvas",
      type: "data-request",
      id: "request-1",
      method: "agentRequest",
      payload: { prompt: "Change it" },
    });

    expect(onDataRequest).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "request-1",
        ok: false,
        error: "Agent requests require a user action",
      }),
    );
  });

  it("does not apply the data-request timeout to approved agent requests", async () => {
    vi.useFakeTimers();
    try {
      const post = vi.fn();
      let approve: (value: unknown) => void = () => {};
      const onDataRequest = vi.fn(
        () =>
          new Promise<unknown>((resolve) => {
            approve = resolve;
          }),
      );
      const route = createCanvasHostMessageRouter({
        post,
        callbacks: () => ({ onDataRequest }),
        hasUserActivation: () => true,
        openExternal: vi.fn(),
      });

      const routed = route({
        channel: "posthog-canvas",
        type: "data-request",
        id: "request-1",
        method: "agentRequest",
        payload: { prompt: "Change it" },
      });

      // Elapse well past the 30s generic data-request timeout: an approval
      // dialog can sit open this long, and the canvas must not be told it
      // failed while a later approval could still start the run.
      await vi.advanceTimersByTimeAsync(60_000);
      expect(post).not.toHaveBeenCalled();

      // The viewer's approval is the only response the canvas receives.
      approve({ requestOutcome: "new_run" });
      await routed;
      expect(post).toHaveBeenCalledTimes(1);
      expect(post).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "request-1",
          ok: true,
          result: { requestOutcome: "new_run" },
        }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not count a pending agent request against the concurrency limit", async () => {
    const post = vi.fn();
    const onDataRequest = vi.fn((method: string) =>
      method === "agentRequest"
        ? new Promise<unknown>(() => {}) // dialog open, never settles
        : Promise.resolve(null),
    );
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({ onDataRequest }),
      hasUserActivation: () => true,
      openExternal: vi.fn(),
    });

    void route({
      channel: "posthog-canvas",
      type: "data-request",
      id: "agent-1",
      method: "agentRequest",
      payload: { prompt: "Change it" },
    });

    // With the dialog sitting unanswered, the canvas's ordinary reads must
    // still get all 8 slots: none may be rejected for runtime limits.
    await Promise.all(
      Array.from({ length: 8 }, (_, i) =>
        route({
          channel: "posthog-canvas",
          type: "data-request",
          id: `query-${i}`,
          method: "stateGet",
          payload: { scope: "user", key: `k${i}` },
        }),
      ),
    );

    expect(post).toHaveBeenCalledTimes(8);
    expect(post.mock.calls.every(([message]) => message.ok === true)).toBe(
      true,
    );
  });
});
