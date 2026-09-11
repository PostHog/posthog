import { describe, expect, it, vi } from "vitest";
import { createCanvasHostMessageRouter } from "./canvasHostMessageRouter";

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

  it("bounds pending connectors separately from ordinary requests", async () => {
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
    await route({
      channel: "posthog-canvas",
      type: "data-request",
      id: "overflow",
      method: "connectorCall",
      payload: { provider: "github", tool: "list_pull_requests" },
    });
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "overflow",
        ok: false,
        error: "Canvas data request exceeds runtime limits",
      }),
    );
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
    completions.forEach((resolve) => {
      resolve(null);
    });
    await Promise.all(requests);
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
