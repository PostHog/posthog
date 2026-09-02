import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildContinuationPrompt,
  buildImplementPrompt,
  buildKickoffPreamble,
  buildKickoffPrompt,
  buildMeasurePrompt,
  buildReportReminderPrompt,
  buildResumePrompt,
  countPromptRequests,
  extractLastAgentTurnText,
  parseMetricReport,
  parsePlanReport,
  parseResearchReport,
  parseStreamedMetricReports,
} from "./prompts";
import type {
  AutoresearchConfig,
  AutoresearchIteration,
  AutoresearchRun,
} from "./schemas";

function makeConfig(
  overrides: Partial<AutoresearchConfig> = {},
): AutoresearchConfig {
  return {
    taskId: "task-1",
    direction: "maximize",
    targetValue: null,
    maxIterations: 8,
    implementModel: null,
    measureModel: null,
    implementEffort: null,
    measureEffort: null,
    instructions: "Optimize the HTTP handler throughput benchmark.",
    ...overrides,
  };
}

function makeIteration(
  index: number,
  value: number,
  summary: string | null = null,
): AutoresearchIteration {
  return {
    index,
    value,
    bestValue: value,
    delta: null,
    summary,
    hypothesis: null,
    plan: null,
    approach: null,
    at: index,
  };
}

function makeRun(
  iterations: AutoresearchIteration[],
  configOverrides: Partial<AutoresearchConfig> = {},
): AutoresearchRun {
  return {
    id: "ar-1",
    config: makeConfig(configOverrides),
    status: "running",
    metricName: "requests per second",
    metricUnit: null,
    phase: null,
    originalModel: null,
    originalEffort: null,
    researchFindings: [],
    iterations,
    startedAt: 0,
    endedAt: null,
    endReason: null,
    interruptedReason: null,
    lastError: null,
  };
}

function report(value: string, summary?: string): string {
  const lines = [`metric: ${value}`];
  if (summary) lines.push(`summary: ${summary}`);
  return ["```autoresearch", ...lines, "```"].join("\n");
}

describe("parseMetricReport", () => {
  it("parses a report with value and summary", () => {
    const text = `I switched to a faster parser.\n\n${report("1234.5", "swapped JSON parser")}`;
    expect(parseMetricReport(text)).toEqual({
      value: 1234.5,
      name: null,
      unit: null,
      summary: "swapped JSON parser",
      hypothesis: null,
      plan: null,
      approach: null,
    });
  });

  it("parses a report without a summary", () => {
    expect(parseMetricReport(report("42"))).toEqual({
      value: 42,
      name: null,
      unit: null,
      summary: null,
      hypothesis: null,
      plan: null,
      approach: null,
    });
  });

  it("returns null when there is no report block", () => {
    expect(parseMetricReport("All done, metric: 42")).toBeNull();
  });

  it("returns null when the metric is not a number", () => {
    expect(parseMetricReport(report("fast"))).toBeNull();
  });

  it("uses the last well-formed block when several exist", () => {
    const text = `${report("1")}\nthen I measured again\n${report("2", "final")}`;
    expect(parseMetricReport(text)).toEqual({
      value: 2,
      name: null,
      unit: null,
      summary: "final",
      hypothesis: null,
      plan: null,
      approach: null,
    });
  });

  it("falls back to an earlier valid block when the last one is malformed", () => {
    const text = `${report("7", "good")}\n${report("not-a-number")}`;
    expect(parseMetricReport(text)).toEqual({
      value: 7,
      name: null,
      unit: null,
      summary: "good",
      hypothesis: null,
      plan: null,
      approach: null,
    });
  });

  it("strips thousands separators", () => {
    expect(parseMetricReport(report("1,234,567"))?.value).toBe(1234567);
  });

  it("parses negative and decimal values", () => {
    expect(parseMetricReport(report("-12.75"))?.value).toBe(-12.75);
  });

  it("accepts mixed-case keys and extra whitespace", () => {
    const text = "```autoresearch\n  Metric :  99 \n  Summary : tidy \n```";
    expect(parseMetricReport(text)).toEqual({
      value: 99,
      name: null,
      unit: null,
      summary: "tidy",
      hypothesis: null,
      plan: null,
      approach: null,
    });
  });

  it("parses experiment context from a metric report", () => {
    expect(
      parseMetricReport(
        "```autoresearch\nmetric: 90\nsummary: memoized selectors\nhypothesis: repeated selectors dominate render time\nplan: memoize selectors and rerun the benchmark\napproach: rendering\n```",
      ),
    ).toEqual({
      value: 90,
      name: null,
      unit: null,
      summary: "memoized selectors",
      hypothesis: "repeated selectors dominate render time",
      plan: "memoize selectors and rerun the benchmark",
      approach: "rendering",
    });
  });

  it("ignores research only blocks", () => {
    expect(
      parseMetricReport(
        "```autoresearch\ntype: research\nsummary: traced routing\nfinding: routes are contributed by UI modules\n```",
      ),
    ).toBeNull();
  });
});

describe("parseStreamedMetricReports", () => {
  it("ignores a report at the streaming tail", () => {
    expect(parseStreamedMetricReports(report("10", "draft"))).toEqual([]);
  });

  it("accepts a report once the next iteration starts", () => {
    expect(
      parseStreamedMetricReports(
        `${report("10", "baseline")}\nIteration 2 starts now.`,
      ),
    ).toEqual([expect.objectContaining({ value: 10, summary: "baseline" })]);
  });
});

describe("parseResearchReport", () => {
  it("parses a valid research checkpoint", () => {
    expect(
      parseResearchReport(
        "```autoresearch\ntype: research\nsummary: traced routing\nfinding: routes are contributed by UI modules\nnext: inspect the contribution\n```",
      ),
    ).toEqual({
      summary: "traced routing",
      finding: "routes are contributed by UI modules",
      nextStep: "inspect the contribution",
      area: null,
    });
  });

  it.each([
    ["missing type", "summary: traced routing\nfinding: found it"],
    ["missing summary", "type: research\nfinding: found it"],
    ["missing finding", "type: research\nsummary: traced routing"],
  ])("rejects a checkpoint with %s", (_name, body) => {
    expect(
      parseResearchReport(`\`\`\`autoresearch\n${body}\n\`\`\``),
    ).toBeNull();
  });

  it("uses the last valid research checkpoint", () => {
    const text = [
      "```autoresearch",
      "type: research",
      "summary: first",
      "finding: initial finding",
      "```",
      "```autoresearch",
      "type: research",
      "summary: second",
      "finding: final finding",
      "```",
    ].join("\n");

    expect(parseResearchReport(text)).toEqual({
      summary: "second",
      finding: "final finding",
      nextStep: null,
      area: null,
    });
  });
});

describe("parsePlanReport", () => {
  it("parses a complete experiment plan", () => {
    expect(
      parsePlanReport(
        "```autoresearch\ntype: plan\nhypothesis: repeated queries dominate latency\nplan: cache the query and rerun the benchmark\napproach: caching\n```",
      ),
    ).toEqual({
      hypothesis: "repeated queries dominate latency",
      plan: "cache the query and rerun the benchmark",
      approach: "caching",
    });
  });

  it("requires every plan field", () => {
    expect(
      parsePlanReport(
        "```autoresearch\ntype: plan\nhypothesis: repeated queries dominate latency\n```",
      ),
    ).toBeNull();
  });
});

function promptEvent(ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      id: ts,
      method: "session/prompt",
      params: { prompt: [{ type: "text", text: "go" }] },
    },
  };
}

function agentChunkEvent(ts: number, text: string): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text },
        },
      },
    },
  };
}

function toolCallEvent(ts: number): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: { sessionUpdate: "tool_call", content: { type: "text" } },
      },
    },
  };
}

describe("extractLastAgentTurnText", () => {
  it("joins agent chunks after the most recent prompt", () => {
    const events = [
      promptEvent(1),
      agentChunkEvent(2, "old turn"),
      promptEvent(3),
      agentChunkEvent(4, "Hello "),
      agentChunkEvent(5, "world"),
    ];
    expect(extractLastAgentTurnText(events)).toBe("Hello world");
  });

  it("ignores non-message updates within the turn", () => {
    const events = [
      promptEvent(1),
      agentChunkEvent(2, "a"),
      toolCallEvent(3),
      agentChunkEvent(4, "b"),
    ];
    expect(extractLastAgentTurnText(events)).toBe("ab");
  });

  it("returns an empty string when the turn produced no text", () => {
    expect(extractLastAgentTurnText([promptEvent(1), toolCallEvent(2)])).toBe(
      "",
    );
  });

  it("collects all chunks when no prompt request exists", () => {
    const events = [agentChunkEvent(1, "x"), agentChunkEvent(2, "y")];
    expect(extractLastAgentTurnText(events)).toBe("xy");
  });

  it("returns an empty string for an empty transcript", () => {
    expect(extractLastAgentTurnText([])).toBe("");
  });
});

describe("buildKickoffPrompt", () => {
  it("includes the direction, budget, and instructions", () => {
    const prompt = buildKickoffPrompt(makeConfig());
    expect(prompt).toContain("the metric defined by the brief");
    expect(prompt).toContain("maximize");
    expect(prompt).toContain("up to 8 iterations");
    expect(prompt).toContain("Optimize the HTTP handler throughput benchmark.");
    expect(prompt).toContain("```autoresearch");
  });

  it("mentions the target only when one is set", () => {
    expect(buildKickoffPrompt(makeConfig())).not.toContain("Target:");
    expect(buildKickoffPrompt(makeConfig({ targetValue: 500 }))).toContain(
      "reaches 500",
    );
    expect(
      buildKickoffPrompt(
        makeConfig({ direction: "minimize", targetValue: 500 }),
      ),
    ).toContain("drops to 500");
  });

  it("ends with the instructions so hosts can substitute prompt content", () => {
    const config = makeConfig();
    const prompt = buildKickoffPrompt(config);
    expect(prompt.endsWith(config.instructions)).toBe(true);
    expect(prompt).toBe(
      `${buildKickoffPreamble(config)}\n\n${config.instructions}`,
    );
  });
});

describe("buildKickoffPreamble", () => {
  it("carries the full protocol but no instructions", () => {
    const preamble = buildKickoffPreamble(makeConfig());
    expect(preamble).toContain("name: <short metric label");
    expect(preamble).toContain("```autoresearch");
    expect(preamble).toContain("up to 8 iterations");
    expect(preamble).not.toContain(
      "Optimize the HTTP handler throughput benchmark.",
    );
  });

  it("requires autoresearch pull request attribution", () => {
    const preamble = buildKickoffPreamble(makeConfig());
    expect(preamble).toContain("feat(autoresearch): <descriptive title>");
    expect(preamble).toContain('"Created with Autoresearch."');
  });
});

describe("buildContinuationPrompt", () => {
  it("states the next iteration number, best, and last values", () => {
    const run = makeRun([
      makeIteration(1, 100, "baseline"),
      makeIteration(2, 140, "cache layer"),
    ]);
    const prompt = buildContinuationPrompt(run);
    expect(prompt).toContain("iteration 3 of 8");
    expect(prompt).toContain("Best so far: 140 (iteration 2)");
    expect(prompt).toContain("Last: 140");
    expect(prompt).toContain("cache layer");
    expect(prompt).toContain("```autoresearch");
  });

  it("preserves the pull request convention in later iterations", () => {
    const run = makeRun([makeIteration(1, 100, "baseline")]);
    expect(buildContinuationPrompt(run)).toContain(
      "feat(autoresearch): <descriptive title>",
    );
    expect(buildImplementPrompt(run)).toContain('"Created with Autoresearch."');
    expect(buildMeasurePrompt(run)).toContain(
      "feat(autoresearch): <descriptive title>",
    );
  });

  it("requests an experiment plan in every implementation path", () => {
    const run = makeRun([makeIteration(1, 100, "baseline")]);
    expect(buildContinuationPrompt(run)).toContain("type: plan");
    expect(buildImplementPrompt(run)).toContain("type: plan");
    expect(buildMeasurePrompt(run)).toContain(
      "Repeat the hypothesis, plan, and approach",
    );
  });

  it("only lists the five most recent iterations", () => {
    const run = makeRun(
      Array.from({ length: 7 }, (_, i) => makeIteration(i + 1, i + 1)),
    );
    const prompt = buildContinuationPrompt(run);
    expect(prompt).not.toContain("Iteration 2:");
    expect(prompt).toContain("Iteration 3:");
    expect(prompt).toContain("Iteration 7:");
  });
});

describe("buildReportReminderPrompt", () => {
  it("names the metric and repeats the block format", () => {
    const prompt = buildReportReminderPrompt(makeRun([]));
    expect(prompt).toContain('"requests per second"');
    expect(prompt).toContain("```autoresearch");
  });
});

describe("buildResumePrompt", () => {
  it("states the interruption cause and carries the continuation", () => {
    const run = makeRun([makeIteration(1, 100, "baseline")]);
    const prompt = buildResumePrompt(run, "rate-limited");
    expect(prompt).toContain("a usage limit was hit");
    expect(prompt).toContain("resuming now");
    expect(prompt).toContain("iteration 2 of 8");
    expect(prompt).toContain("```autoresearch");
  });

  it("warns about half-applied changes from the aborted iteration", () => {
    const prompt = buildResumePrompt(makeRun([]), "app-restart");
    expect(prompt).toContain("the app restarted");
    expect(prompt).toContain("partially applied change");
  });
});

describe("unit parsing and rendering", () => {
  it("parses the unit line", () => {
    const text =
      "```autoresearch\nmetric: 412\nname: bundle size\nunit: kB\nsummary: trimmed deps\n```";
    expect(parseMetricReport(text)).toEqual({
      value: 412,
      name: "bundle size",
      unit: "kB",
      summary: "trimmed deps",
      hypothesis: null,
      plan: null,
      approach: null,
    });
  });

  it("ignores a unit that is too long to be a unit", () => {
    const text =
      "```autoresearch\nmetric: 5\nunit: kilobytes of gzipped production javascript\n```";
    expect(parseMetricReport(text)?.unit).toBeNull();
  });

  it("includes the unit in continuation history once known", () => {
    const run = {
      ...makeRun([makeIteration(1, 100, "baseline")]),
      metricUnit: "ms",
    };
    const prompt = buildContinuationPrompt(run);
    expect(prompt).toContain("Iteration 1: 100 ms. baseline");
    expect(prompt).toContain("Best so far: 100 ms (iteration 1)");
    expect(prompt).toContain("Last: 100 ms");
  });

  it("mentions the unit line in the protocol example", () => {
    expect(buildKickoffPreamble(makeConfig())).toContain(
      "unit: <the metric's unit",
    );
  });
});

describe("countPromptRequests", () => {
  it("counts only session/prompt requests", () => {
    expect(countPromptRequests([])).toBe(0);
    expect(
      countPromptRequests([
        promptEvent(1),
        agentChunkEvent(2, "hi"),
        toolCallEvent(3),
        promptEvent(4),
        agentChunkEvent(5, "done"),
      ]),
    ).toBe(2);
  });
});
