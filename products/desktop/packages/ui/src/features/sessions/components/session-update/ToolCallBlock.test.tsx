import { ServiceProvider } from "@posthog/di/react";
import { createPiToolCallRecord, posthogToolMeta } from "@posthog/shared";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { Container } from "inversify";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { MCP_TOOL_BLOCK_COMPONENT } from "./identifiers";
import { ToolCallBlock } from "./ToolCallBlock";
import type { ToolViewProps } from "./toolCallUtils";

// EditToolView's leaf renderers reach outside the unit under test: FileMentionChip
// pulls workspace/tRPC context, and CodePreview mounts a web component that needs
// a real CSSStyleSheet. The edit-routing test only cares that ToolCallBlock
// dispatched to EditToolView, so stub both to their load-bearing inputs.
vi.mock("./FileMentionChip", () => ({
  FileMentionChip: ({ filePath }: { filePath: string }) => (
    <span>{filePath}</span>
  ),
}));
vi.mock("./CodePreview", () => ({
  CodePreview: () => <span>code-preview</span>,
}));

function renderBlock(
  toolCall: ToolCall,
  mcpToolBlock?: (props: ToolViewProps & { mcpToolName: string }) => ReactNode,
  turnComplete = true,
) {
  const container = new Container();
  if (mcpToolBlock) {
    container.bind(MCP_TOOL_BLOCK_COMPONENT).toConstantValue(mcpToolBlock);
  }
  return render(
    <ServiceProvider container={container}>
      <Theme>
        <ToolCallBlock toolCall={toolCall} turnComplete={turnComplete} />
      </Theme>
    </ServiceProvider>,
  );
}

describe("ToolCallBlock routing", () => {
  it("routes a codex MCP descriptor to the bound McpToolBlock with the canonical name", () => {
    const seen: { mcpToolName?: string } = {};
    const McpToolBlock = vi.fn(
      ({ mcpToolName }: ToolViewProps & { mcpToolName: string }) => {
        seen.mcpToolName = mcpToolName;
        return <div>mcp-block-rendered</div>;
      },
    );

    renderBlock(
      {
        toolCallId: "tc-mcp",
        title: "exec",
        kind: "other",
        status: "completed",
        rawInput: { query: "select 1" },
        _meta: posthogToolMeta({
          toolName: "mcp__posthog__exec",
          mcp: { server: "posthog", tool: "exec" },
        }),
      },
      McpToolBlock,
    );

    expect(screen.getByText("mcp-block-rendered")).toBeInTheDocument();
    expect(seen.mcpToolName).toBe("mcp__posthog__exec");
  });

  it("falls back to the generic tool view for an MCP call when no McpToolBlock is bound", () => {
    renderBlock({
      toolCallId: "tc-mcp-fallback",
      title: "exec",
      kind: "other",
      status: "completed",
      rawInput: { query: "select 1" },
      _meta: posthogToolMeta({
        toolName: "mcp__posthog__exec",
        mcp: { server: "posthog", tool: "exec" },
      }),
    });

    // The MCP branch renders the title in its header; assert it lands somewhere
    // (i.e. the call did not blow up unbound) without an MCP block present.
    expect(screen.getByText("exec")).toBeInTheDocument();
  });

  it("renders a directory listing as a list, not a read", () => {
    renderBlock({
      toolCallId: "tc-list",
      title: "List files",
      kind: "list",
      status: "completed",
      locations: [{ path: "/repo" }],
    });

    expect(screen.getByText("List files in")).toBeInTheDocument();
    expect(screen.queryByText("Read")).toBeNull();
  });

  it("routes a codex edit tool call (no _meta) to the edit view with diff stats", () => {
    renderBlock({
      toolCallId: "tc-edit",
      title: "Edit a.ts",
      kind: "edit",
      status: "completed",
      content: [{ type: "diff", path: "a.ts", oldText: "x", newText: "y" }],
      locations: [{ path: "a.ts" }],
    });

    expect(screen.getByText("a.ts")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("-1")).toBeInTheDocument();
  });

  it("routes a codex execute tool call (no _meta) to the execute view header", () => {
    renderBlock({
      toolCallId: "tc-exec",
      title: "run tests",
      kind: "execute",
      status: "completed",
      rawInput: { command: "pnpm test", description: "Run tests" },
      content: [{ type: "content", content: { type: "text", text: "ok" } }],
    });

    expect(screen.getByText("Run tests")).toBeInTheDocument();
    expect(screen.getByText("pnpm test")).toBeInTheDocument();
  });

  it.each([
    {
      title: "workflow",
      details: {
        name: "release-check",
        currentPhase: "Review",
        agents: [
          {
            id: 1,
            label: "Review API",
            agent: "Explore",
            status: "running",
          },
          {
            id: 2,
            label: "Review UI",
            agent: "Explore",
            status: "running",
          },
        ],
      },
      expectedTitle: "Running workflow: Release check",
      expectedSummary: undefined,
      expectedStep: "Review API",
    },
    {
      title: "subagent",
      details: {
        mode: "single",
        results: [
          {
            runId: "run-1",
            agent: "Explore",
            task: "Inspect the API",
            state: "running",
          },
        ],
      },
      expectedTitle: "Running 1 subagent",
      expectedSummary: undefined,
      expectedStep: "Explore",
    },
  ])(
    "renders structured Pi $title updates with the session tool style",
    ({ title, details, expectedTitle, expectedSummary, expectedStep }) => {
      renderBlock(
        {
          toolCallId: `tc-${title}`,
          title,
          kind: "other",
          status: "in_progress",
          details,
        },
        undefined,
        false,
      );

      expect(screen.getByText(expectedTitle)).toBeInTheDocument();
      if (expectedSummary) {
        expect(screen.getByText(`· ${expectedSummary}`)).toBeInTheDocument();
      }
      expect(screen.getByText(expectedStep)).toBeInTheDocument();
    },
  );

  it("shows a failed parallel child reason while other agents continue", () => {
    renderBlock(
      {
        toolCallId: "tc-partial-subagent-failure",
        title: "subagent",
        kind: "other",
        status: "in_progress",
        details: {
          mode: "parallel",
          results: [
            {
              runId: "run-1",
              agent: "Explore",
              task: "Inspect the API",
              state: "failed",
              errorMessage: "Authentication failed",
            },
            {
              runId: "run-2",
              agent: "Plan",
              task: "Review the UI",
              state: "running",
            },
          ],
        },
      },
      undefined,
      false,
    );

    expect(screen.getByText("Running 2 subagents")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Explore"));
    expect(screen.getByText(/Authentication failed/)).toBeInTheDocument();
  });

  it("summarizes a completed workflow while its details are collapsed", () => {
    renderBlock({
      toolCallId: "tc-completed-workflow",
      title: "workflow",
      kind: "other",
      status: "completed",
      details: {
        name: "authorization-review",
        done: true,
        agents: [
          {
            id: 1,
            label: "API review",
            agent: "Explore",
            objective: "Check auth routes",
            status: "done",
          },
          {
            id: 2,
            label: "UI review",
            agent: "Explore",
            objective: "Check permission controls",
            status: "done",
          },
        ],
      },
    });

    expect(
      screen.getByText("Ran workflow: Authorization review"),
    ).toBeInTheDocument();
  });

  it.each(["in_progress" as const, "completed" as const])(
    "explains a %s workflow with no agent details in its collapsed header",
    (status) => {
      renderBlock({
        toolCallId: `tc-empty-${status}-workflow`,
        title: "workflow",
        kind: "other",
        status,
        details: {
          name: "authorization-review",
          agents: [],
        },
      });

      expect(
        screen.getByText("Ran workflow: Authorization review"),
      ).toBeInTheDocument();
    },
  );

  it("explains a rejected subagent call instead of 'No agents started' when the tool resolves without spawning an agent", () => {
    renderBlock({
      toolCallId: "tc-subagent-rejected",
      title: "subagent",
      kind: "other",
      status: "completed",
      details: {
        mode: "single",
        results: [],
      },
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: 'Unknown agent "Researcher". Available agents: Explore (bundled), Plan (bundled), General (bundled)',
          },
        },
      ],
    });

    expect(screen.getByText(/Unknown agent "Researcher"/)).toBeInTheDocument();
    expect(screen.queryByText("· No agents started")).toBeNull();
  });

  it("marks a rejected subagent call as failed rather than completed once expanded", () => {
    const { container } = renderBlock({
      toolCallId: "tc-subagent-rejected-step",
      title: "subagent",
      kind: "other",
      status: "completed",
      details: {
        mode: "single",
        results: [],
      },
      content: [
        {
          type: "content",
          content: { type: "text", text: 'Unknown agent "Researcher".' },
        },
      ],
    });

    fireEvent.click(screen.getByRole("button"));

    expect(container.querySelector(".text-red-9")).not.toBeNull();
    expect(container.querySelector(".text-green-9")).toBeNull();
  });

  it("keeps a per-agent step detail short instead of the full task sentence", () => {
    const longTask =
      "Find project-local Pi agent definitions under .pi/agents, if any. List each file and summarize its declared role and capabilities from its frontmatter or content in detail.";
    renderBlock(
      {
        toolCallId: "tc-subagent-long-task",
        title: "subagent",
        kind: "other",
        status: "in_progress",
        details: {
          mode: "single",
          results: [
            {
              runId: "run-1",
              agent: "Explore",
              task: longTask,
              state: "running",
            },
          ],
        },
      },
      undefined,
      false,
    );

    expect(screen.queryByText(longTask)).toBeNull();
    expect(screen.getByText(/Find project-local Pi agent/)).toBeInTheDocument();
  });

  it.each([
    ["running", "in_progress" as const, false],
    ["completed", "completed" as const, true],
    ["canceled", "completed" as const, true],
  ])(
    "shows the intended work and completed actions for a %s subagent",
    (_state, status, turnComplete) => {
      const task =
        "List files in the repository root directory only. Return a concise inventory.";
      renderBlock(
        {
          toolCallId: `tc-subagent-description-${status}`,
          title: "subagent",
          kind: "other",
          status,
          details: {
            mode: "single",
            results: [
              {
                runId: "run-1",
                agent: "Explore",
                task,
                description: "Listing root files",
                toolCalls: [
                  createPiToolCallRecord(
                    {
                      id: "call-read-1",
                      name: "read",
                      arguments: { path: "/repo/one.ts" },
                    },
                    "completed",
                  ),
                  createPiToolCallRecord(
                    {
                      id: "call-read-2",
                      name: "read",
                      arguments: { path: "/repo/two.ts" },
                    },
                    _state === "running" ? "in_progress" : "completed",
                  ),
                ],
                state: _state === "canceled" ? "aborted" : _state,
              },
            ],
          },
        },
        undefined,
        turnComplete,
      );

      if (status !== "in_progress") {
        fireEvent.click(screen.getByRole("button"));
      }
      fireEvent.click(screen.getByText("Explore"));

      expect(screen.getAllByText(/Listing root files/)).toHaveLength(1);
      expect(screen.getAllByText("Read")).toHaveLength(2);
      expect(screen.queryByText(task)).toBeNull();
    },
  );

  it("expands each completed subagent independently", () => {
    renderBlock({
      toolCallId: "tc-parallel-subagent-tool-calls",
      title: "subagent",
      kind: "other",
      status: "completed",
      details: {
        mode: "parallel",
        results: [
          {
            runId: "run-1",
            agent: "Explore",
            task: "Read the root files",
            description: "Reading root files",
            toolCalls: [
              createPiToolCallRecord(
                {
                  id: "call-read",
                  name: "read",
                  arguments: { path: "/repo/root.ts" },
                },
                "completed",
              ),
            ],
            state: "completed",
          },
          {
            runId: "run-2",
            agent: "Explore",
            task: "Run a dependency check",
            description: "Checking dependencies",
            toolCalls: [
              createPiToolCallRecord(
                {
                  id: "call-bash",
                  name: "bash",
                  arguments: { command: "pnpm why dependency" },
                },
                "completed",
              ),
            ],
            state: "completed",
          },
        ],
      },
    });

    expect(screen.getByText("Ran 2 subagents")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Ran 2 subagents"));
    fireEvent.click(screen.getAllByText("Explore")[0]);

    expect(screen.getByText("Read")).toBeInTheDocument();
    expect(screen.queryByText("Bash")).toBeNull();

    fireEvent.click(screen.getAllByText("Explore")[1]);

    expect(screen.getByText(/pnpm why dependency/)).toBeInTheDocument();
  });

  it("shows a canceled workflow through the structured view instead of the raw script fallback", () => {
    renderBlock({
      toolCallId: "tc-canceled-workflow",
      title: "workflow",
      kind: "other",
      status: "completed",
      rawInput: { script: "export const meta = { name: 'demo' }" },
      details: {
        name: "demo",
        done: true,
        cancelled: true,
        agents: [
          {
            id: 1,
            label: "Local agent discovery",
            agent: "Explore",
            status: "done",
          },
          {
            id: 2,
            label: "Orchestration usage discovery",
            agent: "Explore",
            status: "aborted",
          },
        ],
      },
      content: [
        {
          type: "content",
          content: { type: "text", text: "Workflow was canceled" },
        },
      ],
    });

    expect(
      screen.getByText("Ran workflow: Demo, canceled"),
    ).toBeInTheDocument();
    expect(screen.queryByText("(Failed)")).toBeNull();
    expect(screen.queryByText(/export const meta/)).toBeNull();
  });

  it("shows the workflow failure in its collapsed header", () => {
    renderBlock({
      toolCallId: "tc-failed-workflow",
      title: "workflow",
      kind: "other",
      status: "failed",
      details: {
        name: "authorization-review",
        done: true,
        agents: [],
      },
      content: [
        {
          type: "content",
          content: {
            type: "text",
            text: "Workflow failed: Missing synthesis output",
          },
        },
      ],
    });

    expect(
      screen.getByText("Workflow failed: Missing synthesis output"),
    ).toBeInTheDocument();
  });

  it("renders Codex orchestration calls as operations rather than subagents", () => {
    renderBlock({
      toolCallId: "tc-wait-agent",
      title: "Wait for subagents",
      kind: "other",
      status: "completed",
      _meta: posthogToolMeta({ toolName: "wait_agent" }),
    });

    expect(screen.getByText("Wait for subagents")).toBeInTheDocument();
    expect(screen.queryByText(/^Subagent/)).not.toBeInTheDocument();
  });

  it("shows the failure instead of live buttons when a show_actions call is denied", () => {
    renderBlock({
      toolCallId: "tc-show-denied",
      title: "show_actions",
      kind: "other",
      status: "failed",
      rawInput: {
        actions: [
          { kind: "open_space", label: "Open the space", channel_id: "chan" },
        ],
      },
      content: [
        {
          type: "content",
          content: { type: "text", text: "This tool has been blocked." },
        },
      ],
      _meta: posthogToolMeta({
        toolName: "mcp__local__show_actions",
        mcp: { server: "local", tool: "show_actions" },
      }),
    });

    // The standard tool view renders its failure marker...
    expect(screen.getByText("(Failed)")).toBeInTheDocument();
    // ...rather than the clickable button the block was supposed to withhold.
    expect(screen.queryByText("Open the space")).toBeNull();
  });
});
