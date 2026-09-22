import { posthogToolMeta } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  isUploadArtifactCall,
  type PrCreationCandidate,
  readCreatedPrUrl,
  readUploadedArtifactName,
} from "./inlineArtifacts";

const PR_URL = "https://github.com/PostHog/posthog/pull/82584";

function call(
  overrides: Partial<PrCreationCandidate> & { command?: string },
): PrCreationCandidate {
  const { command, ...rest } = overrides;
  return {
    status: "completed",
    meta: posthogToolMeta({ toolName: "Bash" }),
    rawInput: command === undefined ? {} : { command },
    outputText: "",
    ...rest,
  };
}

function mcpMeta(tool: string) {
  return posthogToolMeta({
    toolName: `mcp__github__${tool}`,
    mcp: { server: "github", tool },
  });
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

  it("detects an upload_artifact MCP call", () => {
    expect(isUploadArtifactCall(mcpMeta("upload_artifact"))).toBe(true);
    expect(isUploadArtifactCall(mcpMeta("create_pull_request"))).toBe(false);
  });

  it.each([
    {
      name: "gh pr create",
      call: call({
        command: "gh pr create --fill",
        outputText: `Creating pull request\n${PR_URL}`,
      }),
      expected: PR_URL,
    },
    {
      name: "an MCP create-pull-request tool",
      call: call({
        command: undefined,
        meta: mcpMeta("create_pull_request"),
        rawInput: { title: "Fix" },
        outputText: `{"html_url":"${PR_URL}"}`,
      }),
      expected: PR_URL,
    },
    {
      name: "reading someone else's pull request",
      call: call({
        command: "gh pr view 82584 --json url",
        outputText: PR_URL,
      }),
      expected: null,
    },
    {
      // `create_pull_request_review` contains the creation tool's whole name
      // and answers with the url of the PR it reviewed.
      name: "reviewing someone else's pull request over MCP",
      call: call({
        command: undefined,
        meta: mcpMeta("create_pull_request_review"),
        rawInput: { pullNumber: 82584, event: "COMMENT" },
        outputText: `{"html_url":"${PR_URL}"}`,
      }),
      expected: null,
    },
    {
      name: "a command that only talks about creating one",
      call: call({
        command: `gh pr comment 82584 --body "next time run gh pr create"`,
        outputText: PR_URL,
      }),
      expected: null,
    },
    {
      name: "a creation chained after a push",
      call: call({
        command: "git push -u origin work && gh pr create --fill",
        outputText: PR_URL,
      }),
      expected: PR_URL,
    },
    {
      name: "a creation still in flight",
      call: call({
        command: "gh pr create --fill",
        status: "in_progress",
        outputText: "",
      }),
      expected: null,
    },
    {
      name: "a creation that printed no url",
      call: call({
        command: "gh pr create --fill",
        outputText: "pull request create failed",
      }),
      expected: null,
    },
  ])("reads a created pull request from $name", ({ call, expected }) => {
    expect(readCreatedPrUrl(call)).toBe(expected);
  });
});
