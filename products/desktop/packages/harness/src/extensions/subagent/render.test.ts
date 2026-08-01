import type { Theme } from "@earendil-works/pi-coding-agent";
import { beforeEach, describe, expect, it } from "vitest";
import {
  formatUsageStats,
  renderSubagentCall,
  renderSubagentResult,
} from "./render";
import type { SingleRunResult } from "./run-agent";
import { __resetAgentRunsForTesting, upsertAgentRun } from "./status-registry";

function makeTheme(): Theme {
  return {
    fg: (_color: string, text: string) => text,
    bg: (_color: string, text: string) => text,
    bold: (text: string) => text,
    italic: (text: string) => text,
    underline: (text: string) => text,
    inverse: (text: string) => text,
    strikethrough: (text: string) => text,
  } as unknown as Theme;
}

function successResult(
  overrides: Partial<SingleRunResult> = {},
): SingleRunResult {
  return {
    runId: "run-1",
    startedAt: Date.now(),
    agent: "scout",
    task: "look around",
    exitCode: 0,
    messages: [
      {
        role: "assistant",
        content: [{ type: "text", text: "found it" }],
      } as never,
    ],
    stderr: "",
    usage: {
      input: 100,
      output: 50,
      cacheRead: 0,
      cacheWrite: 0,
      cost: 0.01,
      contextTokens: 150,
      turns: 1,
    },
    ...overrides,
  };
}

describe("formatUsageStats", () => {
  it("formats a full set of usage fields", () => {
    const text = formatUsageStats(
      {
        input: 1200,
        output: 500,
        cacheRead: 0,
        cacheWrite: 0,
        cost: 0.0123,
        contextTokens: 2000,
        turns: 2,
      },
      "anthropic/opus",
    );
    expect(text).toContain("2 turns");
    expect(text).toContain("$0.0123");
    expect(text).toContain("anthropic/opus");
  });

  it("returns an empty string when there's nothing to show", () => {
    expect(
      formatUsageStats({
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        cost: 0,
        contextTokens: 0,
        turns: 0,
      }),
    ).toBe("");
  });
});

describe("renderSubagentCall", () => {
  const theme = makeTheme();

  beforeEach(() => {
    __resetAgentRunsForTesting();
  });

  it("renders single mode", () => {
    const component = renderSubagentCall(
      { agent: "scout", task: "find the auth code" },
      theme,
    );
    const lines = component.render(80);
    expect(lines.join("\n")).toContain("scout");
    expect(lines.join("\n")).toContain("find the auth code");
  });

  it("renders parallel mode with a task count", () => {
    const component = renderSubagentCall(
      {
        tasks: [
          { agent: "scout", task: "a" },
          { agent: "reviewer", task: "b" },
        ],
      },
      theme,
    );
    const lines = component.render(80);
    expect(lines.join("\n")).toContain("scout");
    expect(lines.join("\n")).toContain("reviewer");
  });

  it("never exceeds the given width, even for very long tasks", () => {
    const component = renderSubagentCall(
      { agent: "scout", task: "x".repeat(500) },
      theme,
    );
    for (const line of component.render(40)) {
      expect(line.length).toBeLessThanOrEqual(40);
    }
  });

  it("numbers each task in parallel mode, so the result slot's numbers line up positionally", () => {
    const component = renderSubagentCall(
      {
        tasks: [
          { agent: "scout", task: "a" },
          { agent: "scout", task: "b" },
        ],
      },
      theme,
    );
    const lines = component.render(80);
    expect(lines[0]).toContain("1. ");
    expect(lines[1]).toContain("2. ");
  });

  it("stays static while a matching run is active", () => {
    upsertAgentRun({
      runId: "run-live",
      agent: "scout",
      task: "a",
      startedAt: Date.now() - 5000,
      usage: {
        input: 900,
        output: 100,
        cacheRead: 0,
        cacheWrite: 0,
        cost: 0,
        contextTokens: 0,
        turns: 1,
      },
      messages: [],
    });

    const text = renderSubagentCall({ agent: "scout", task: "a" }, theme)
      .render(80)
      .join("\n");
    expect(text).not.toContain("tokens");
    expect(text).not.toContain("5s");
  });
});

describe("renderSubagentResult", () => {
  const theme = makeTheme();

  it("falls back to plain text when there are no results", () => {
    const component = renderSubagentResult(
      {
        content: [{ type: "text", text: "nothing" }],
        details: { mode: "single", results: [] },
      },
      { expanded: false, isPartial: false },
      theme,
    );
    expect(component.render(80).join("\n")).toContain("nothing");
  });

  it("renders a collapsed single result without repeating the agent name", () => {
    const component = renderSubagentResult(
      {
        content: [{ type: "text", text: "done" }],
        details: { mode: "single", results: [successResult()] },
      },
      { expanded: false, isPartial: false },
      theme,
    );
    const text = component.render(80).join("\n");
    expect(text).toContain("Done");
    // The call slot already names the agent (`Agent(task)`); the collapsed
    // result must not repeat it on its own line.
    expect(text).not.toContain("scout");
  });

  it("renders an expanded single result with the task and output", () => {
    const component = renderSubagentResult(
      {
        content: [{ type: "text", text: "done" }],
        details: { mode: "single", results: [successResult()] },
      },
      { expanded: true, isPartial: false },
      theme,
    );
    const text = component.render(80).join("\n");
    expect(text).toContain("scout");
    expect(text).toContain("look around");
    expect(text).toContain("found it");
  });

  it("renders parallel results without a stale runId hint (runId only ever accompanies empty results)", () => {
    const component = renderSubagentResult(
      {
        content: [{ type: "text", text: "done" }],
        details: {
          mode: "parallel",
          results: [successResult(), successResult({ agent: "reviewer" })],
        },
      },
      { expanded: false, isPartial: false },
      theme,
    );
    const text = component.render(80).join("\n");
    expect(text).not.toContain("run-1");
    // Positionally aligned with the call slot's numbered task list instead
    // of repeating each agent's name in the result too.
    expect(text).toContain("1. Done");
    expect(text).toContain("2. Done");
  });

  it("marks a failed result distinctly from a running one", () => {
    const failed = successResult({
      exitCode: 1,
      stopReason: "error",
      errorMessage: "boom",
    });
    const running = successResult({ exitCode: -1, agent: "worker" });
    const component = renderSubagentResult(
      {
        content: [{ type: "text", text: "..." }],
        details: { mode: "parallel", results: [failed, running] },
      },
      { expanded: false, isPartial: false },
      theme,
    );
    const text = component.render(80).join("\n");
    expect(text).toContain("Failed");
    expect(text).toContain("boom");
    expect(text).toContain("Running");
  });

  it("never exceeds the given width, even for a very long task or error message", () => {
    const failed = successResult({
      exitCode: 1,
      stopReason: "error",
      task: "first line\nsecond line\n".repeat(20),
      errorMessage: "boom ".repeat(100),
    });
    const component = renderSubagentResult(
      {
        content: [{ type: "text", text: "..." }],
        details: { mode: "single", results: [failed] },
      },
      { expanded: true, isPartial: false },
      theme,
    );
    for (const line of component.render(40)) {
      expect(line.length).toBeLessThanOrEqual(40);
    }
  });
});
