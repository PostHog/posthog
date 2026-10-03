import { describe, expect, it } from "vitest";
import { detectInlineArtifact, type InlineArtifact } from "./inlineArtifacts";

const PR_URL = "https://github.com/PostHog/posthog/pull/82584";

function mcpMeta(tool: string) {
  return { claudeCode: { toolName: `mcp__github__${tool}` } };
}

describe("detectInlineArtifact", () => {
  it("detects an upload_artifact call regardless of status", () => {
    expect(
      detectInlineArtifact({
        meta: {
          claudeCode: { toolName: "mcp__posthog-code-tools__upload_artifact" },
        },
        status: "running",
        args: { name: "report.csv" },
      }),
    ).toEqual({ kind: "upload" });
  });

  it.each<{
    name: string;
    toolData: Parameters<typeof detectInlineArtifact>[0];
    expected: InlineArtifact | null;
  }>([
    {
      name: "gh pr create",
      toolData: {
        meta: { claudeCode: { toolName: "Bash" } },
        status: "completed",
        args: { command: "gh pr create --fill" },
        result: `Creating pull request\n${PR_URL}`,
      },
      expected: { kind: "pr", url: PR_URL },
    },
    {
      name: "an MCP create_pull_request tool",
      toolData: {
        meta: mcpMeta("create_pull_request"),
        status: "completed",
        args: { title: "Fix" },
        result: { html_url: PR_URL },
      },
      expected: { kind: "pr", url: PR_URL },
    },
    {
      // create_pull_request_review contains the creation tool's whole name and
      // returns the url of the PR it reviewed — not this run's deliverable.
      name: "reviewing someone else's PR over MCP",
      toolData: {
        meta: mcpMeta("create_pull_request_review"),
        status: "completed",
        args: { pullNumber: 82584, event: "COMMENT" },
        result: { html_url: PR_URL },
      },
      expected: null,
    },
    {
      // The url sits inside a gh pr comment body, not in a command position.
      name: "a comment that only mentions creating one",
      toolData: {
        meta: { claudeCode: { toolName: "Bash" } },
        status: "completed",
        args: {
          command: `gh pr comment 82584 --body "next time run gh pr create"`,
        },
        result: PR_URL,
      },
      expected: null,
    },
    {
      name: "reading someone else's PR",
      toolData: {
        meta: { claudeCode: { toolName: "Bash" } },
        status: "completed",
        args: { command: "gh pr view 82584 --json url" },
        result: PR_URL,
      },
      expected: null,
    },
    {
      name: "a creation still running",
      toolData: {
        meta: { claudeCode: { toolName: "Bash" } },
        status: "running",
        args: { command: "gh pr create --fill" },
        result: "",
      },
      expected: null,
    },
  ])("resolves $name", ({ toolData, expected }) => {
    expect(detectInlineArtifact(toolData)).toEqual(expected);
  });
});
