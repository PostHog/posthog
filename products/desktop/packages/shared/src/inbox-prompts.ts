interface BuildDiscussReportPromptOptions {
  reportId: string;
  reportLink: string;
  question?: string;
}

export function buildDiscussReportPrompt({
  reportId,
  reportLink,
  question,
}: BuildDiscussReportPromptOptions): string {
  const trimmedQuestion = question?.trim();
  const intro = `Discuss PostHog inbox report ${reportId} ([inbox item](${reportLink})). Use the inbox MCP tools to fetch the report,`;
  const guard =
    " If you can't fetch the report, say so instead of guessing what it contains.";
  const body = trimmedQuestion
    ? `${intro} then answer this first: ${trimmedQuestion}`
    : `${intro} then give me a brief readout and ask what I want to dig into.`;
  return `${body}${guard}`;
}
