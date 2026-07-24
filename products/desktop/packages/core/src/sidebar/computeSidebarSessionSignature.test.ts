import { describe, expect, it } from "vitest";
import {
  computeSidebarSessionSignature,
  type TaskSession,
} from "./buildSidebarData";

type SigInput = Record<string, TaskSession & { taskId?: string }>;

function sig(sessions: Record<string, unknown>): string {
  return computeSidebarSessionSignature(sessions as SigInput);
}

describe("computeSidebarSessionSignature", () => {
  it("ignores fields the sidebar doesn't render (e.g. events)", () => {
    const before = sig({
      r1: { taskId: "t1", isPromptPending: true, events: [1] },
    });
    const after = sig({
      r1: { taskId: "t1", isPromptPending: true, events: [1, 2, 3, 4] },
    });
    expect(after).toBe(before);
  });

  it("changes when isPromptPending flips", () => {
    const a = sig({ r1: { taskId: "t1", isPromptPending: false } });
    const b = sig({ r1: { taskId: "t1", isPromptPending: true } });
    expect(a).not.toBe(b);
  });

  it("changes when the pending-permission count changes", () => {
    const a = sig({ r1: { taskId: "t1", pendingPermissions: { size: 0 } } });
    const b = sig({ r1: { taskId: "t1", pendingPermissions: { size: 1 } } });
    expect(a).not.toBe(b);
  });

  it("changes when cloud status or PR url changes", () => {
    const a = sig({ r1: { taskId: "t1", cloudStatus: "running" } });
    const b = sig({ r1: { taskId: "t1", cloudStatus: "completed" } });
    expect(a).not.toBe(b);

    const c = sig({ r1: { taskId: "t1", cloudOutput: { pr_url: "x" } } });
    const d = sig({ r1: { taskId: "t1", cloudOutput: { pr_url: "y" } } });
    expect(c).not.toBe(d);
  });

  it("skips sessions without a taskId", () => {
    expect(sig({ r1: { isPromptPending: true } })).toBe("");
  });
});
