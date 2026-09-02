import type { Signal, SignalReport } from "@posthog/shared/types";

// A cloud first message rides through task-run creation as plain text; keep the
// inlined report bounded so a signal-heavy report can't balloon the request.
const MAX_SUMMARY_CHARS = 10_000;
const MAX_SIGNALS = 20;
const MAX_SIGNAL_CHARS = 1_500;

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}… [truncated]`;
}

/**
 * Serialize a report into the markdown block a Discuss session starts with, so
 * the agent has the whole report in context without a fetch round-trip: title,
 * triage metadata, the full summary, and the contributing evidence signals
 * (bounded — anything past the caps is called out as omitted).
 */
export function buildReportPromptContext(
  report: SignalReport,
  signals: Signal[],
): string {
  const blocks: string[] = [];
  blocks.push(`# Report: ${report.title?.trim() || "Untitled report"}`);

  const meta = [
    `ID: ${report.id}`,
    `Status: ${report.status}`,
    report.priority ? `Priority: ${report.priority}` : null,
    report.actionability ? `Actionability: ${report.actionability}` : null,
    `Created: ${report.created_at}`,
  ]
    .filter(Boolean)
    .join(" · ");
  blocks.push(meta);

  blocks.push("## Summary");
  const summary = report.summary?.trim();
  blocks.push(summary ? truncate(summary, MAX_SUMMARY_CHARS) : "(no summary)");

  if (signals.length > 0) {
    const shown = signals.slice(0, MAX_SIGNALS);
    blocks.push(
      `## Evidence (${signals.length} signal${signals.length === 1 ? "" : "s"})`,
    );
    shown.forEach((signal, index) => {
      blocks.push(
        `### Signal ${index + 1} — ${signal.source_product} (${signal.timestamp})`,
      );
      blocks.push(truncate(signal.content.trim(), MAX_SIGNAL_CHARS));
    });
    if (signals.length > shown.length) {
      blocks.push(
        `(${signals.length - shown.length} more signals omitted — fetch them with the inbox MCP tools if needed.)`,
      );
    }
  }

  return blocks.join("\n\n");
}
