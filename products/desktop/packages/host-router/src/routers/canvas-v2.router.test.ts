import { describe, expect, it, vi } from "vitest";
import { canvasV2Router } from "./canvas-v2.router";

describe("canvasV2Router", () => {
  it.each([
    [400, "BAD_REQUEST"],
    [503, "INTERNAL_SERVER_ERROR"],
  ])("preserves the retry decision for HTTP %s", async (status, code) => {
    const service = {
      appendOps: vi
        .fn()
        .mockRejectedValue(
          Object.assign(new Error("Request failed"), { status }),
        ),
    };
    const caller = canvasV2Router.createCaller({
      container: { get: <T>() => service as T },
    });

    await expect(
      caller.appendOps({
        id: "board",
        ops: [],
        actor: { kind: "user" },
        baseSeq: 0,
      }),
    ).rejects.toMatchObject({
      code,
      message: "Request failed",
    });
  });
});
