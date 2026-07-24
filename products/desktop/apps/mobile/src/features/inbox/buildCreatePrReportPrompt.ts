interface BuildCreatePrReportPromptOptions {
  summary?: string | null;
  feedback?: string;
}

export function buildCreatePrReportPrompt({
  summary,
  feedback,
}: BuildCreatePrReportPromptOptions): string {
  const base = `Act on this signal report. Investigate the root cause, implement the fix, and open a PR if appropriate.\n\n${summary ?? ""}`;
  const trimmed = feedback?.trim();
  if (!trimmed) return base;
  return `${base}\n\nAdditional feedback from the user (take this into account, including any questions raised in the report thread):\n${trimmed}`;
}
