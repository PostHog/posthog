import type { NotificationTarget } from "@posthog/platform/notifications";
import { describe, expect, it } from "vitest";
import type { z } from "zod";
import { notificationTargetSchema } from "./notification.router";

// The tRPC input schema and the platform union are maintained by hand in two
// places; this asserts they stay structurally identical (assignable both ways).
type SchemaTarget = z.infer<typeof notificationTargetSchema>;

// Compile-time parity: each must be assignable to the other.
const _toPlatform: NotificationTarget = {} as SchemaTarget;
const _toSchema: SchemaTarget = {} as NotificationTarget;
void _toPlatform;
void _toSchema;

describe("notificationTargetSchema", () => {
  it("parses both target kinds and rejects unknown kinds", () => {
    expect(
      notificationTargetSchema.parse({ kind: "task", taskId: "t1" }).kind,
    ).toBe("task");
    expect(
      notificationTargetSchema.parse({
        kind: "canvas",
        channelId: "c1",
        dashboardId: "d1",
      }).kind,
    ).toBe("canvas");
    expect(
      notificationTargetSchema.safeParse({ kind: "nope", id: "x" }).success,
    ).toBe(false);
  });
});
