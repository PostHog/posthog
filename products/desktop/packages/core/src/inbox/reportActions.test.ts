import { describe, expect, it } from "vitest";
import {
  buildCreatePrReportPrompt,
  buildDiscussReportPrompt,
} from "./reportActions";

describe("buildCreatePrReportPrompt", () => {
  it("embeds the report web URL as a clickable backlink when provided", () => {
    const prompt = buildCreatePrReportPrompt({
      reportId: "abc123",
      reportUrl: "https://us.posthog.com/project/2/inbox/abc123",
    });
    expect(prompt).toContain(
      "([inbox item](https://us.posthog.com/project/2/inbox/abc123))",
    );
  });

  it("never embeds a posthog-code:// deep link", () => {
    const prompt = buildCreatePrReportPrompt({
      reportId: "abc123",
      reportUrl: "https://us.posthog.com/project/2/inbox/abc123",
    });
    expect(prompt).not.toContain("posthog-code://");
  });

  it("omits the inline link when no report URL is known", () => {
    const prompt = buildCreatePrReportPrompt({ reportId: "abc123" });
    expect(prompt).not.toContain("([inbox item]");
    expect(prompt).toContain("Act on PostHog inbox report abc123.");
  });

  it("references the inbox MCP tools so the agent fetches the detail itself", () => {
    const prompt = buildCreatePrReportPrompt({ reportId: "abc123" });
    expect(prompt).toContain("inbox MCP tools");
  });

  it("asks the agent to open a PR", () => {
    const prompt = buildCreatePrReportPrompt({ reportId: "abc123" });
    expect(prompt).toMatch(/open a PR/i);
  });

  it("tells the agent to continue an existing linked PR instead of opening a duplicate", () => {
    const prompt = buildCreatePrReportPrompt({ reportId: "abc123" });
    expect(prompt).toContain("implementation_pr_url");
    expect(prompt).toMatch(/gh pr checkout/i);
    expect(prompt).toMatch(/do not open a second PR/i);
  });

  it("tells the agent to stop rather than guess if the report can't be fetched", () => {
    const prompt = buildCreatePrReportPrompt({ reportId: "abc123" });
    expect(prompt).toMatch(/can't fetch the report/i);
    expect(prompt).toMatch(/instead of guessing/i);
  });

  it("appends user feedback when provided", () => {
    const prompt = buildCreatePrReportPrompt({
      reportId: "abc123",
      feedback: "Use the v2 endpoint, not v1.",
    });
    expect(prompt).toMatch(/Additional feedback from the user/i);
    expect(prompt).toContain("Use the v2 endpoint, not v1.");
  });

  it.each([
    { label: "undefined", feedback: undefined },
    { label: "empty string", feedback: "" },
    { label: "whitespace only", feedback: "   " },
  ])("omits the feedback section when feedback is $label", ({ feedback }) => {
    const base = buildCreatePrReportPrompt({ reportId: "abc123" });
    const prompt = buildCreatePrReportPrompt({
      reportId: "abc123",
      feedback,
    });
    expect(prompt).toBe(base);
    expect(prompt).not.toMatch(/Additional feedback/i);
  });
});

describe("buildDiscussReportPrompt", () => {
  it("uses the production deeplink scheme outside dev builds", () => {
    const prompt = buildDiscussReportPrompt({
      reportId: "abc123",
      isDevBuild: false,
    });
    expect(prompt).toContain("posthog-code://inbox/abc123");
  });

  it("uses the dev deeplink scheme in dev builds", () => {
    const prompt = buildDiscussReportPrompt({
      reportId: "abc123",
      isDevBuild: true,
    });
    expect(prompt).toContain("posthog-code-dev://inbox/abc123");
  });

  it("falls back to the open-ended readout when no question is given", () => {
    const prompt = buildDiscussReportPrompt({
      reportId: "abc123",
      isDevBuild: false,
    });
    expect(prompt).toContain("give me a brief readout");
  });

  it("incorporates a trimmed question when provided", () => {
    const prompt = buildDiscussReportPrompt({
      reportId: "abc123",
      question: "  Why is conversion dropping?  ",
      isDevBuild: false,
    });
    expect(prompt).toContain("answer this first: Why is conversion dropping?");
    expect(prompt).not.toContain("brief readout");
  });

  it("treats a whitespace-only question as no question", () => {
    const prompt = buildDiscussReportPrompt({
      reportId: "abc123",
      question: "   ",
      isDevBuild: false,
    });
    expect(prompt).toContain("brief readout");
  });

  it("appends a slugified title suffix to the deep link", () => {
    const prompt = buildDiscussReportPrompt({
      reportId: "abc123",
      reportTitle: "fix(inbox): Add foo",
      isDevBuild: false,
    });
    expect(prompt).toContain("posthog-code://inbox/abc123/fix-inbox--Add-foo");
  });

  it("omits the slug suffix when the title is blank", () => {
    const prompt = buildDiscussReportPrompt({
      reportId: "abc123",
      reportTitle: "   ",
      isDevBuild: false,
    });
    expect(prompt).toContain("posthog-code://inbox/abc123)");
  });

  it("tells the agent to say so rather than guess if the report can't be fetched", () => {
    const withQuestion = buildDiscussReportPrompt({
      reportId: "abc123",
      question: "Why is conversion dropping?",
      isDevBuild: false,
    });
    const withoutQuestion = buildDiscussReportPrompt({
      reportId: "abc123",
      isDevBuild: false,
    });
    expect(withQuestion).toMatch(/can't fetch the report/i);
    expect(withoutQuestion).toMatch(/can't fetch the report/i);
  });
});
