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

  it("queues an over-cap data request and runs it once a slot frees", async () => {
    const post = vi.fn();
    const resolvers = new Map<string, (value: unknown) => void>();
    const onDataRequest = vi.fn(
      (_method: string, payload: unknown) =>
        new Promise<unknown>((resolve) =>
          resolvers.set((payload as { key: string }).key, resolve),
        ),
    );
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({ onDataRequest }),
      hasUserActivation: () => true,
      openExternal: vi.fn(),
    });
    const tick = (): Promise<void> =>
      new Promise((resolve) => setTimeout(resolve, 0));
    const fire = (key: string): Promise<void> =>
      route({
        channel: "posthog-canvas",
        type: "data-request",
        id: key,
        method: "stateGet",
        payload: { scope: "user", key },
      });

    // Fill all 8 slots with requests that stay in flight.
    for (let i = 0; i < 8; i++) {
      void fire(`slot-${i}`);
    }
    // The 9th request is over the cap: it must wait for a slot, not fail.
    void fire("queued");
    await tick();
    expect(onDataRequest).toHaveBeenCalledTimes(8);
    expect(post).not.toHaveBeenCalled();

    // Freeing one slot hands it to the queued request, which now runs.
    resolvers.get("slot-0")?.(null);
    await tick();
    expect(onDataRequest).toHaveBeenCalledTimes(9);
    expect(post).toHaveBeenCalledTimes(1);

    resolvers.get("queued")?.({ value: 1 });
    await tick();
    expect(post).toHaveBeenCalledTimes(2);
    expect(post.mock.calls.every(([message]) => message.ok === true)).toBe(
      true,
    );
  });

  it("runs a queued request against the handler that received it, not the current one", async () => {
    const post = vi.fn();
    const resolvers = new Map<string, (value: unknown) => void>();
    // Canvas A's handler stays in flight so it occupies slots; canvas B's must
    // never be reached by a request A issued.
    const handlerA = vi.fn(
      (_method: string, payload: unknown) =>
        new Promise<unknown>((resolve) =>
          resolvers.set((payload as { key: string }).key, resolve),
        ),
    );
    const handlerB = vi.fn().mockResolvedValue({ from: "B" });
    let activeHandler = handlerA;
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({ onDataRequest: activeHandler }),
      hasUserActivation: () => true,
      openExternal: vi.fn(),
    });
    const tick = (): Promise<void> =>
      new Promise((resolve) => setTimeout(resolve, 0));
    const fire = (key: string): Promise<void> =>
      route({
        channel: "posthog-canvas",
        type: "data-request",
        id: key,
        method: "stateGet",
        payload: { scope: "user", key },
      });

    // Fill all 8 slots, then queue a 9th while canvas A is still current.
    for (let i = 0; i < 8; i++) {
      void fire(`slot-${i}`);
    }
    void fire("queued");
    await tick();
    expect(handlerA).toHaveBeenCalledTimes(8);

    // The warm pool swaps the live handler to canvas B before a slot frees.
    activeHandler = handlerB;
    resolvers.get("slot-0")?.(null);
    await tick();

    // The queued request must run against A — the canvas that issued it — even
    // though B is now the router's current handler.
    expect(handlerA).toHaveBeenCalledTimes(9);
    expect(handlerA).toHaveBeenLastCalledWith("stateGet", {
      scope: "user",
      key: "queued",
    });
    expect(handlerB).not.toHaveBeenCalled();
  });

  it("rejects a data request once the wait queue is also full", async () => {
    const post = vi.fn();
    // Nothing ever resolves, so every slot and queue place stays occupied.
    const onDataRequest = vi.fn(() => new Promise<unknown>(() => {}));
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({ onDataRequest }),
      hasUserActivation: () => true,
      openExternal: vi.fn(),
    });
    const fire = (id: string): Promise<void> =>
      route({
        channel: "posthog-canvas",
        type: "data-request",
        id,
        method: "stateGet",
        payload: { scope: "user", key: id },
      });

    // 8 slots + 64 queued fill the bridge without a single rejection.
    for (let i = 0; i < 8 + 64; i++) {
      void fire(`req-${i}`);
    }
    expect(post).not.toHaveBeenCalled();

    // One past the bound is refused rather than queued, so a runaway loop
    // can't pile up unbounded work.
    await fire("overflow");
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "overflow",
        ok: false,
        error: "Canvas data request exceeds runtime limits",
      }),
    );
  });
});
