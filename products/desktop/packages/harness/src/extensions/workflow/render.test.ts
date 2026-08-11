import type {
  AgentToolResult,
  Theme,
  ToolRenderResultOptions,
} from "@earendil-works/pi-coding-agent";
import { describe, expect, it } from "vitest";
import type { WorkflowAgentStatus, WorkflowSnapshot } from "./render";
import {
  artifactProvenance,
  groupByPhase,
  previewOf,
  renderWorkflowCall,
  renderWorkflowResult,
  schemaSummary,
} from "./render";

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

function agentStatus(
  overrides: Partial<WorkflowAgentStatus> = {},
): WorkflowAgentStatus {
  return {
    id: 1,
    label: "recon",
    agent: "Explore",
    status: "done",
    ...overrides,
  };
}

function snapshot(overrides: Partial<WorkflowSnapshot> = {}): WorkflowSnapshot {
  return { phases: [], agents: [], logs: [], done: true, ...overrides };
}

function textOf(component: unknown): string {
  // pi-tui Text stores its content; Container nests children. Render via the
  // string we handed in — both components expose it through `render()` lines.
  const rendered = component as { render?: (width: number) => string[] };
  if (typeof rendered.render === "function")
    return rendered
      .render(200)
      .map((line) => line.trimEnd())
      .join("\n");
  return String(component);
}

function renderResult(
  details: WorkflowSnapshot,
  expanded: boolean,
  text = "Workflow completed.",
): string {
  return textOf(
    renderWorkflowResult(
      {
        content: [{ type: "text", text }],
        details,
      } as unknown as AgentToolResult<WorkflowSnapshot>,
      { expanded } as ToolRenderResultOptions,
      makeTheme(),
    ),
  );
}

describe("previewOf", () => {
  it.each([
    ["string first line", "line one\nline two", "line one"],
    ["objects as JSON", { a: 1 }, '{"a":1}'],
    ["null", null, undefined],
    ["empty string", "   ", undefined],
  ])("handles %s", (_name, input, expected) => {
    expect(previewOf(input)).toBe(expected);
  });

  it("truncates long lines", () => {
    const preview = previewOf("x".repeat(200)) as string;
    expect(preview.length).toBeLessThan(80);
    expect(preview.endsWith("…")).toBe(true);
  });
});

describe("metadata summaries", () => {
  it("summarizes output contracts and artifact provenance compactly", () => {
    expect(schemaSummary({ type: "object", required: ["files", "ok"] })).toBe(
      "object; required: files, ok",
    );
    expect(
      artifactProvenance(
        snapshot({
          phases: ["Scan"],
          phaseMetadata: { Scan: { produces: ["report"] } },
          agents: [
            agentStatus({
              label: "inventory",
              phase: "Scan",
              produces: "files",
            }),
          ],
        }),
      ),
    ).toEqual(["files ← inventory (Scan)", "report ← Scan"]);
  });
});

describe("groupByPhase", () => {
  it("groups by phase preserving first-seen order", () => {
    const groups = groupByPhase([
      agentStatus({ id: 1, phase: "Scan" }),
      agentStatus({ id: 2, phase: "Audit" }),
      agentStatus({ id: 3, phase: "Scan" }),
    ]);
    expect(groups.map((g) => g.title)).toEqual(["Scan", "Audit"]);
    expect(groups[0].agents.map((a) => a.id)).toEqual([1, 3]);
  });
});

describe("renderWorkflowCall", () => {
  it("shows the workflow name from meta", () => {
    const text = textOf(
      renderWorkflowCall(
        { script: "const meta = { name: 'audit_routes' }" },
        makeTheme(),
      ),
    );
    expect(text).toContain("workflow");
    expect(text).toContain("audit_routes");
  });
});

describe("renderWorkflowResult", () => {
  it("falls back to content text without agents", () => {
    expect(renderResult(snapshot(), false, "plain text")).toBe("plain text");
  });

  it("collapsed view shows status, phase headers, and recent agents", () => {
    const text = renderResult(
      snapshot({
        name: "audit",
        agents: [
          agentStatus({ id: 1, phase: "Scan", label: "inventory" }),
          agentStatus({
            id: 2,
            phase: "Audit",
            label: "auth check",
            status: "error",
          }),
        ],
        tokensSpent: 12_000,
      }),
      false,
    );
    expect(text).toContain("workflow audit 2/2 agents");
    expect(text).toContain("12k tok");
    expect(text).toContain("Scan 1/1");
    expect(text).toContain("Audit 1/1");
    expect(text).toContain("inventory");
    expect(text).toContain("auth check");
  });

  it("collapsed view elides earlier agents beyond the cap", () => {
    const agents = Array.from({ length: 10 }, (_, i) =>
      agentStatus({ id: i + 1, phase: "Scan", label: `agent-${i + 1}` }),
    );
    const text = renderResult(snapshot({ agents }), false);
    expect(text).toContain("(+4 more)");
    expect(text).not.toContain("agent-1 ");
    expect(text).toContain("agent-10");
  });

  it("collapsed completed view includes a final-result preview without Ctrl+O", () => {
    const text = renderResult(
      snapshot({
        agents: [agentStatus()],
        result: "Architecture: portable core with thin hosts.",
      }),
      false,
    );
    expect(text).toContain("Result");
    expect(text).toContain("Architecture: portable core with thin hosts.");
    expect(text).not.toContain("Ctrl+O");
  });

  it("expanded completed view includes compact artifact provenance", () => {
    const text = renderResult(
      snapshot({
        agents: [
          agentStatus({ phase: "Scan", label: "inventory", produces: "files" }),
        ],
      }),
      true,
    );
    expect(text).toContain("Artifacts");
    expect(text).toContain("files ← inventory (Scan)");
  });

  it("collapsed completed view keeps artifact provenance out of the compact state", () => {
    const text = renderResult(
      snapshot({ agents: [agentStatus({ produces: "files" })] }),
      false,
    );
    expect(text).not.toContain("Artifacts");
  });

  it("expanded view includes previews, logs, and the result", () => {
    const text = renderResult(
      snapshot({
        agents: [
          agentStatus({
            phase: "Scan",
            resultPreview: "found 3 routers",
          }),
        ],
        logs: ["agent x failed: nope"],
      }),
      true,
      "Final synthesized result",
    );
    expect(text).toContain("found 3 routers");
    expect(text).toContain("Logs");
    expect(text).toContain("agent x failed: nope");
    expect(text).toContain("Final synthesized result");
  });

  it("shows current phase while running", () => {
    const text = renderResult(
      snapshot({
        done: false,
        currentPhase: "Audit",
        agents: [agentStatus({ status: "running", phase: "Audit" })],
      }),
      false,
    );
    expect(text).toContain("0/1 agents");
    expect(text).toContain("Audit");
    expect(text).not.toContain("Ctrl+O");
  });

  it("does not repeat the current phase name on the top status line", () => {
    // Regression test: the phase name used to appear both on the overall
    // status line ("workflow 1/2 agents · Audit") and again on the
    // phase-group header directly below it ("◐ Audit 0/1") — pure
    // duplication when only one phase is active. The phase-group header is
    // now the only place it appears.
    const text = renderResult(
      snapshot({
        name: "audit",
        done: false,
        currentPhase: "Audit",
        agents: [agentStatus({ status: "running", phase: "Audit" })],
      }),
      false,
    );
    const statusLine = text.split("\n")[0];
    expect(statusLine).not.toContain("Audit");
    expect(statusLine).toContain("0/1 agents");
  });

  it("animates the running icon with pi's own spinner frames, not a static hourglass", () => {
    const text = renderResult(
      snapshot({
        done: false,
        agents: [agentStatus({ status: "running", phase: "Scan" })],
      }),
      false,
    );
    expect(text).not.toContain("\u23f3"); // no more static hourglass
    expect(text).toMatch(
      /[\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f]/,
    );
  });

  it("uses the same spinner for an in-progress phase header, not a static half-moon", () => {
    const text = renderResult(
      snapshot({
        done: false,
        agents: [
          agentStatus({ status: "done", phase: "Scan" }),
          agentStatus({ id: 2, status: "running", phase: "Audit" }),
        ],
      }),
      false,
    );
    expect(text).not.toContain("\u25d0"); // no more static half-moon
    expect(text).toMatch(
      /[\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f]/,
    );
  });

  it.each([
    ["collapsed", false],
    ["expanded", true],
  ])(
    "never renders a line wider than the given width even with an oversized label (%s)",
    (_name, expanded) => {
      const width = 80;
      const component = renderWorkflowResult(
        {
          content: [{ type: "text", text: "done" }],
          details: snapshot({
            name: "audit",
            agents: [
              agentStatus({
                label: "x".repeat(300),
                phase: "Scan",
                resultPreview: "y".repeat(300),
              }),
            ],
          }),
        } as unknown as AgentToolResult<WorkflowSnapshot>,
        { expanded } as ToolRenderResultOptions,
        makeTheme(),
      );
      const rendered = component as { render: (width: number) => string[] };
      for (const line of rendered.render(width)) {
        expect(line.length).toBeLessThanOrEqual(width);
      }
    },
  );

  it("never renders a line wider than the given width for renderWorkflowCall with a long name", () => {
    const width = 40;
    const component = renderWorkflowCall(
      { script: `const meta = { name: '${"n".repeat(300)}' }` },
      makeTheme(),
    );
    for (const line of component.render(width)) {
      expect(line.length).toBeLessThanOrEqual(width);
    }
  });
});
