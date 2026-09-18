import { describe, expect, it, vi } from "vitest";
import { createCanvasHostMessageRouter } from "./canvasHostMessageRouter";

// Lets the router hand a freed slot to the next queued request before the
// test asserts on it.
function flushTimers(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

// Settles every in-flight request, then the ones each freed slot starts.
async function drain(
  completions: Array<(value: unknown) => void>,
): Promise<void> {
  await flushTimers();
  while (completions.length > 0) {
    for (const resolve of completions.splice(0)) resolve(null);
    await flushTimers();
  }
}

describe("createCanvasHostMessageRouter", () => {
  it.each([false, true])(
    "requires activation for task composition (%s)",
    async (active) => {
      const onNavigate = vi.fn();
      const route = createCanvasHostMessageRouter({
        post: vi.fn(),
        callbacks: () => ({ onDataRequest: vi.fn(), onNavigate }),
        hasUserActivation: () => active,
        openExternal: vi.fn(),
      });
      await route({
        channel: "posthog-canvas",
        type: "navigate",
        nav: {
          target: "compose-task",
          prompt: "Inspect this PR",
          repository: "example/app",
        },
      });
      expect(onNavigate).toHaveBeenCalledTimes(active ? 1 : 0);
      if (active)
        expect(onNavigate).toHaveBeenCalledWith({
          target: "compose-task",
          prompt: "Inspect this PR",
          repository: "example/app",
        });
    },
  );

  it.each([false, true])(
    "opens GitHub PR links only after a click (%s)",
    async (active) => {
      const openExternal = vi.fn();
      const route = createCanvasHostMessageRouter({
        post: vi.fn(),
        callbacks: () => ({ onDataRequest: vi.fn() }),
        hasUserActivation: () => active,
        openExternal,
      });
      await route({
        channel: "posthog-canvas",
        type: "open-external",
        url: "https://github.com/example/app/pull/42",
      });
      expect(openExternal).toHaveBeenCalledTimes(active ? 1 : 0);
    },
  );
  it.each([false, true])(
    "requires activation for connector navigation (%s)",
    async (active) => {
      const onNavigate = vi.fn();
      const route = createCanvasHostMessageRouter({
        post: vi.fn(),
        callbacks: () => ({ onDataRequest: vi.fn(), onNavigate }),
        hasUserActivation: () => active,
        openExternal: vi.fn(),
      });
      await route({
        channel: "posthog-canvas",
        type: "navigate",
        nav: { target: "connect", provider: "github" },
      });
      expect(onNavigate).toHaveBeenCalledTimes(active ? 1 : 0);
    },
  );
  it.each([
    [false, false, "tasks.create"],
    [true, true, "tasks.create"],
    [false, false, "tasks.create_and_run"],
    [true, true, "tasks.create_and_run"],
  ])(
    "forwards action invocations only under a user gesture (activation: %s, forwarded: %s, verb: %s)",
    async (hasActivation, forwarded, verb) => {
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
        payload: { verb, payload: { title: "t" } },
      });

      if (forwarded) {
        expect(onDataRequest).toHaveBeenCalledWith("actionInvoke", {
          verb,
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

  it.each(["agentRequest", "connectorCall"] as const)(
    "does not time out %s while waiting for approval",
    async (method) => {
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
          method,
          payload:
            method === "agentRequest"
              ? { prompt: "Change it" }
              : { provider: "mcp:calendar.example.com", tool: "list_events" },
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
    },
  );

  it("queues pending connectors separately from ordinary requests", async () => {
    const post = vi.fn();
    const completions: Array<(value: unknown) => void> = [];
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({
        onDataRequest: (method) =>
          method === "connectorCall"
            ? new Promise((resolve) => completions.push(resolve))
            : Promise.resolve(null),
      }),
      hasUserActivation: () => true,
      openExternal: vi.fn(),
    });
    const requests = Array.from({ length: 8 }, (_, index) =>
      route({
        channel: "posthog-canvas",
        type: "data-request",
        id: `connector-${index}`,
        method: "connectorCall",
        payload: { provider: "github", tool: "list_pull_requests" },
      }),
    );
    const overflow = route({
      channel: "posthog-canvas",
      type: "data-request",
      id: "overflow",
      method: "connectorCall",
      payload: { provider: "github", tool: "list_pull_requests" },
    });
    await route({
      channel: "posthog-canvas",
      type: "data-request",
      id: "ordinary",
      method: "stateGet",
      payload: { key: "data", scope: "user" },
    });
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({ id: "ordinary", ok: true }),
    );
    // The 9th connector holds its turn instead of failing.
    expect(post).not.toHaveBeenCalledWith(
      expect.objectContaining({ id: "overflow" }),
    );

    for (const resolve of completions.splice(0)) resolve(null);
    await Promise.all(requests);
    await flushTimers();
    for (const resolve of completions.splice(0)) resolve(null);
    await overflow;
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({ id: "overflow", ok: true }),
    );
  });

  it("runs a queued request as soon as a slot frees", async () => {
    const post = vi.fn();
    const completions: Array<(value: unknown) => void> = [];
    let concurrent = 0;
    let peakConcurrent = 0;
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({
        onDataRequest: () => {
          concurrent += 1;
          peakConcurrent = Math.max(peakConcurrent, concurrent);
          return new Promise((resolve) => {
            completions.push((value) => {
              concurrent -= 1;
              resolve(value);
            });
          });
        },
      }),
      hasUserActivation: () => true,
      openExternal: vi.fn(),
    });

    // A canvas whose cards fan out past the concurrency cap: every request
    // must still be answered, none dropped.
    const requests = Array.from({ length: 20 }, (_, index) =>
      route({
        channel: "posthog-canvas",
        type: "data-request",
        id: `query-${index}`,
        method: "stateGet",
        payload: { scope: "user", key: `k${index}` },
      }),
    );
    await drain(completions);
    await Promise.all(requests);

    expect(peakConcurrent).toBe(8);
    expect(post).toHaveBeenCalledTimes(20);
    expect(post.mock.calls.every(([message]) => message.ok === true)).toBe(
      true,
    );
  });

  it("names the cause when the queue is full, and marks it retryable", async () => {
    const post = vi.fn();
    const onDataRequestRejected = vi.fn();
    const completions: Array<(value: unknown) => void> = [];
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({
        onDataRequest: () =>
          new Promise((resolve) => {
            completions.push(resolve);
          }),
      }),
      hasUserActivation: () => true,
      openExternal: vi.fn(),
      onDataRequestRejected,
    });

    // 8 in flight plus a full 32-deep queue; the next one has nowhere to wait.
    const requests = Array.from({ length: 40 }, (_, index) =>
      route({
        channel: "posthog-canvas",
        type: "data-request",
        id: `query-${index}`,
        method: "stateGet",
        payload: { scope: "user", key: `k${index}` },
      }),
    );
    await route({
      channel: "posthog-canvas",
      type: "data-request",
      id: "overflow",
      method: "stateGet",
      payload: { scope: "user", key: "overflow" },
    });

    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "overflow",
        ok: false,
        error: "Too many canvas data requests are already waiting",
        retryable: true,
      }),
    );
    expect(onDataRequestRejected).toHaveBeenCalledWith(
      "data-queue-full",
      "stateGet",
    );

    await drain(completions);
    await Promise.all(requests);
  });

  it("stops waiting for a slot before the canvas runtime gives up", async () => {
    vi.useFakeTimers();
    try {
      const post = vi.fn();
      const onDataRequest = vi.fn(() => new Promise<unknown>(() => {}));
      const route = createCanvasHostMessageRouter({
        post,
        callbacks: () => ({ onDataRequest }),
        hasUserActivation: () => true,
        openExternal: vi.fn(),
      });
      for (let index = 0; index < 8; index += 1) {
        void route({
          channel: "posthog-canvas",
          type: "data-request",
          id: `query-${index}`,
          method: "stateGet",
          payload: { scope: "user", key: `k${index}` },
        });
      }
      const queued = route({
        channel: "posthog-canvas",
        type: "data-request",
        id: "queued",
        method: "stateGet",
        payload: { scope: "user", key: "queued" },
      });

      // The canvas runtime abandons a request 30s after it sends it. A wait
      // that outlives the queue limit must come back as the real cause, not
      // as a query the host starts once nobody is listening.
      await vi.advanceTimersByTimeAsync(10_000);
      await queued;

      expect(onDataRequest).toHaveBeenCalledTimes(8);
      expect(post).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "queued",
          ok: false,
          error: "Too many canvas data requests are already waiting",
          retryable: true,
        }),
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it("separates an oversized payload from a full queue, and never retries it", async () => {
    const post = vi.fn();
    const onDataRequest = vi.fn();
    const onDataRequestRejected = vi.fn();
    const route = createCanvasHostMessageRouter({
      post,
      callbacks: () => ({ onDataRequest }),
      hasUserActivation: () => true,
      openExternal: vi.fn(),
      onDataRequestRejected,
    });

    await route({
      channel: "posthog-canvas",
      type: "data-request",
      id: "oversized",
      method: "stateSet",
      payload: { scope: "user", key: "k", value: "x".repeat(64 * 1024 + 1) },
    });

    expect(onDataRequest).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "oversized",
        ok: false,
        error: "Canvas data request is over the 64KB payload limit",
        retryable: false,
      }),
    );
    expect(onDataRequestRejected).toHaveBeenCalledWith(
      "payload-too-large",
      "stateSet",
    );
  });

  it.each(["agentRequest", "connectorCall"] as const)(
    "does not count a pending %s against ordinary request slots",
    async (pendingMethod) => {
      const post = vi.fn();
      const onDataRequest = vi.fn((method: string) =>
        method === pendingMethod
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
        method: pendingMethod,
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
    },
  );
});
