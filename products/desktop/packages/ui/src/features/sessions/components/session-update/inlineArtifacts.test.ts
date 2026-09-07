import { posthogToolMeta } from "@posthog/shared";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { describe, expect, it } from "vitest";
import { readCreatedPrUrl, readUploadedArtifactName } from "./inlineArtifacts";

const PR_URL = "https://github.com/PostHog/posthog/pull/82584";

function bashCall(
  command: string,
  output: string,
  overrides?: Partial<ToolCall>,
): ToolCall {
  return {
    toolCallId: "tc",
    kind: "execute",
    status: "completed",
    rawInput: { command },
    content: [{ type: "content", content: { type: "text", text: output } }],
    _meta: posthogToolMeta({ toolName: "Bash" }),
    ...overrides,
  } as ToolCall;
}

describe("inlineArtifacts", () => {
  it.each([
    {
      name: "an explicit download name",
      input: { path: "/w/out/r.csv", name: "Report.csv" },
      expected: "Report.csv",
    },
    {
      name: "the file's own name",
      input: { path: "/w/out/report.csv" },
      expected: "report.csv",
    },
    {
      name: "a windows path",
      input: { path: "C:\\work\\report.csv" },
      expected: "report.csv",
    },
    { name: "nothing usable", input: { path: "  " }, expected: null },
    { name: "a non-object input", input: "report.csv", expected: null },
  ])("titles an upload from $name", ({ input, expected }) => {
    expect(readUploadedArtifactName(input)).toBe(expected);
  });

  it.each([
    {
      name: "gh pr create",
      call: bashCall("gh pr create --fill", `Creating pull request\n${PR_URL}`),
      expected: PR_URL,
    },
    {
      name: "an MCP create-pull-request tool",
      call: bashCall("", `{"html_url":"${PR_URL}"}`, {
        rawInput: { title: "Fix" },
        _meta: posthogToolMeta({
          toolName: "mcp__github__create_pull_request",
          mcp: { server: "github", tool: "create_pull_request" },
        }),
      }),
      expected: PR_URL,
    },
    // A run that reads, reviews or comments on a PR prints the same URL, and
    // that PR is not something the run produced, so it gets no card.
    {
      name: "reading someone else's pull request",
      call: bashCall("gh pr view 82584 --json url", PR_URL),
      expected: null,
    },
    {
      // `create_pull_request_review` contains the creation tool's whole name
      // and answers with the url of the PR it reviewed.
      name: "reviewing someone else's pull request over MCP",
      call: bashCall("", `{"html_url":"${PR_URL}"}`, {
        rawInput: { pullNumber: 82584, event: "COMMENT" },
        _meta: posthogToolMeta({
          toolName: "mcp__github__create_pull_request_review",
          mcp: { server: "github", tool: "create_pull_request_review" },
        }),
      }),
      expected: null,
    },
    {
      name: "a command that only talks about creating one",
      call: bashCall(
        `gh pr comment 82584 --body "next time run gh pr create"`,
        PR_URL,
      ),
      expected: null,
    },
    {
      name: "a creation chained after a push",
      call: bashCall("git push -u origin work && gh pr create --fill", PR_URL),
      expected: PR_URL,
    },
    {
      name: "a creation still in flight",
      call: bashCall("gh pr create --fill", "", { status: "in_progress" }),
      expected: null,
    },
    {
      name: "a creation that printed no url",
      call: bashCall("gh pr create --fill", "pull request create failed"),
      expected: null,
    },
  ])("reads a created pull request from $name", ({ call, expected }) => {
    expect(readCreatedPrUrl(call)).toBe(expected);
  });
});
