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
});
