import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { analyzeAutoresearchActivity } from "./autoresearchActivity";

function updateEvent(ts: number, update: Record<string, unknown>): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: { update },
    },
  } as AcpMessage;
}

describe("analyzeAutoresearchActivity", () => {
  it("extracts the current plan and classifies observable work", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "agent_message_chunk",
        content: {
          type: "text",
          text: "```autoresearch\ntype: plan\nhypothesis: selectors cause rerenders\nplan: memoize selectors and benchmark\napproach: rendering\n```",
        },
      }),
      updateEvent(3_000, {
        sessionUpdate: "tool_call",
        toolCallId: "search-1",
        title: "Search for selectors",
        kind: "search",
        status: "in_progress",
      }),
      updateEvent(4_000, {
        sessionUpdate: "tool_call_update",
        toolCallId: "search-1",
        status: "completed",
      }),
      updateEvent(5_000, {
        sessionUpdate: "tool_call",
        title: "Edit selector module",
        kind: "edit",
        status: "completed",
      }),
      updateEvent(8_000, {
        sessionUpdate: "tool_call",
        title: "Run benchmark",
        kind: "execute",
        status: "in_progress",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 11_000);

    expect(result.currentPlan).toEqual({
      hypothesis: "selectors cause rerenders",
      plan: "memoize selectors and benchmark",
      approach: "rendering",
    });
    expect(result.items.map((item) => item.kind)).toEqual([
      "measurement",
      "implementation",
      "research",
    ]);
    expect(result.items[0]).toMatchObject({
      label: "Run benchmark",
      running: true,
      active: true,
    });
    expect(result.items[2]).toMatchObject({
      label: "Search for selectors",
      active: false,
      updatedAt: 4_000,
    });
    expect(result.timeByKind).toEqual({
      reasoning: 2_000,
      research: 2_000,
      implementation: 3_000,
      measurement: 3_000,
      execution: 0,
    });
  });

  it("reconciles tool updates and clears active state for completed calls", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        toolCallId: "tool-1",
        title: "Inspect dashboard",
        kind: "read",
        status: "in_progress",
      }),
      updateEvent(3_000, {
        sessionUpdate: "tool_call_update",
        toolCallId: "tool-1",
        status: "completed",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 5_000);

    expect(result.items).toEqual([
      expect.objectContaining({
        id: "tool-1",
        label: "Inspect dashboard",
        running: false,
        active: false,
        at: 2_000,
        updatedAt: 3_000,
      }),
    ]);
  });

  it("preserves running state when a partial tool update omits status", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        toolCallId: "tool-1",
        title: "Execute command",
        kind: "execute",
        status: "in_progress",
      }),
      updateEvent(3_000, {
        sessionUpdate: "tool_call_update",
        toolCallId: "tool-1",
        rawInput: { command: "pnpm test" },
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 5_000);

    expect(result.items).toEqual([
      expect.objectContaining({
        label: "pnpm test",
        kind: "measurement",
        running: true,
        active: true,
      }),
    ]);
  });

  it("uses raw command input instead of a generic execute title", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        toolCallId: "tool-1",
        title: "Execute command",
        kind: "execute",
        rawInput: { command: "apply_patch <<'PATCH'" },
        status: "completed",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 3_000);

    expect(result.items[0]).toMatchObject({
      label: "apply_patch <<'PATCH'",
      kind: "implementation",
      command: true,
    });
  });

  it("classifies shell commands by their observable intent", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        title: "/bin/zsh -lc 'pnpm bench:memory'",
        kind: "execute",
        status: "completed",
      }),
      updateEvent(3_000, {
        sessionUpdate: "tool_call",
        title: "/bin/zsh -lc 'apply_patch <<PATCH'",
        kind: "execute",
        status: "completed",
      }),
      updateEvent(4_000, {
        sessionUpdate: "tool_call",
        title: "/bin/zsh -lc 'git status --short'",
        kind: "execute",
        status: "completed",
      }),
      updateEvent(5_000, {
        sessionUpdate: "tool_call",
        title: "/bin/zsh -lc 'pnpm dev:code'",
        kind: "execute",
        status: "in_progress",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 6_000);
    const kindsByLabel = Object.fromEntries(
      result.items.map((item) => [item.label, item.kind]),
    );

    expect(kindsByLabel).toEqual({
      "/bin/zsh -lc 'pnpm dev:code'": "execution",
      "/bin/zsh -lc 'git status --short'": "research",
      "/bin/zsh -lc 'apply_patch <<PATCH'": "implementation",
      "/bin/zsh -lc 'pnpm bench:memory'": "measurement",
    });
  });

  it("sorts strictly newest-first while marking the newest live command current", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        toolCallId: "server",
        title: "Start dev server",
        kind: "execute",
        status: "in_progress",
      }),
      updateEvent(3_000, {
        sessionUpdate: "tool_call",
        toolCallId: "benchmark",
        title: "Run benchmark",
        kind: "execute",
        status: "in_progress",
      }),
      updateEvent(4_000, {
        sessionUpdate: "tool_call",
        toolCallId: "status",
        title: "Check status",
        kind: "execute",
        status: "completed",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 5_000);

    expect(result.items).toEqual([
      expect.objectContaining({
        label: "Check status",
        running: false,
        active: false,
      }),
      expect.objectContaining({
        label: "Run benchmark",
        running: true,
        active: true,
      }),
      expect.objectContaining({
        label: "Start dev server",
        running: true,
        active: false,
      }),
    ]);
  });

  it("shows no running items when the run is not live", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        toolCallId: "benchmark",
        title: "Run benchmark",
        kind: "execute",
        status: "in_progress",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 5_000, {
      live: false,
    });

    expect(result.items[0]).toMatchObject({ running: false, active: false });
  });

  it("excludes completed pause intervals from observed time", () => {
    const events = [
      updateEvent(3_000, {
        sessionUpdate: "tool_call",
        title: "Search code",
        kind: "search",
        status: "completed",
      }),
      updateEvent(9_000, {
        sessionUpdate: "tool_call",
        title: "Run benchmark",
        kind: "execute",
        status: "completed",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 12_000, {
      pauseIntervals: [{ startedAt: 4_000, endedAt: 8_000 }],
      pausedDurationMs: 4_000,
    });

    expect(result.timeByKind).toEqual({
      reasoning: 2_000,
      research: 2_000,
      implementation: 0,
      measurement: 3_000,
      execution: 0,
    });
  });

  it("caps observed time for legacy runs with untracked paused duration", () => {
    const events = [
      updateEvent(3_000, {
        sessionUpdate: "tool_call",
        title: "Search code",
        kind: "search",
        status: "completed",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, null, 11_000, {
      pausedDurationMs: 6_000,
    });
    const totalObservedMs = Object.values(result.timeByKind).reduce(
      (total, duration) => total + duration,
      0,
    );

    expect(totalObservedMs).toBe(4_000);
  });

  it("shows up to twelve recent timeline items", () => {
    const events = Array.from({ length: 14 }, (_, index) =>
      updateEvent(index + 2_000, {
        sessionUpdate: "tool_call",
        title: `Command ${index + 1}`,
        kind: "execute",
        status: "completed",
      }),
    );

    const result = analyzeAutoresearchActivity(events, 1_000, null, 20_000);

    expect(result.items).toHaveLength(12);
    expect(result.items[0]?.label).toBe("Command 14");
    expect(result.items[11]?.label).toBe("Command 3");
  });

  it("excludes activity after a historical run ended", () => {
    const events = [
      updateEvent(2_000, {
        sessionUpdate: "tool_call",
        title: "Run benchmark",
        kind: "execute",
        status: "completed",
      }),
      updateEvent(6_000, {
        sessionUpdate: "tool_call",
        title: "Later manual edit",
        kind: "edit",
        status: "completed",
      }),
    ];

    const result = analyzeAutoresearchActivity(events, 1_000, 4_000, 10_000);

    expect(result.items).toEqual([
      expect.objectContaining({ label: "Run benchmark" }),
    ]);
    expect(result.timeByKind).toEqual({
      reasoning: 1_000,
      research: 0,
      implementation: 0,
      measurement: 2_000,
      execution: 0,
    });
  });
});
