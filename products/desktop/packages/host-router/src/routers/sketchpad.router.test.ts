import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { describe, expect, it, vi } from "vitest";
import { sketchpadRouter } from "./sketchpad.router";

describe("sketchpadRouter", () => {
  it("leaves ordinary host procedure errors unchanged", async () => {
    const ordinary = router({
      fail: publicProcedure.query(() => {
        throw Object.assign(new Error("Request failed"), { status: 400 });
      }),
    });
    const caller = ordinary.createCaller({
      container: { get: <T>() => undefined as T },
    });
    await expect(caller.fail()).rejects.toMatchObject({
      code: "INTERNAL_SERVER_ERROR",
    });
  });
  it.each([
    [400, "BAD_REQUEST"],
    [401, "UNAUTHORIZED"],
    [403, "FORBIDDEN"],
    [404, "NOT_FOUND"],
    [409, "CONFLICT"],
    [503, "INTERNAL_SERVER_ERROR"],
  ])("preserves the retry decision for HTTP %s", async (status, code) => {
    const service = {
      appendOps: vi
        .fn()
        .mockRejectedValue(
          Object.assign(new Error("Request failed"), { status }),
        ),
    };
    const caller = sketchpadRouter.createCaller({
      container: { get: <T>() => service as T },
    });

    await expect(
      caller.appendOps({
        id: "board",
        baseSeq: 0,
        ops: [],
        actor: { kind: "user" },
      }),
    ).rejects.toMatchObject({
      code,
      message: "Request failed",
    });
  });
});
