/**
 * Pure formatting helpers over `SingleRunResult`. No I/O, no process/agent
 * knowledge beyond the result shape itself.
 */
import type { Message } from "@earendil-works/pi-ai";
import { isFailedResult, type SingleRunResult } from "./run-agent";
import { truncateUtf8 } from "./text-truncate";

const PER_TASK_OUTPUT_CAP = 50 * 1024;

export function getFinalOutput(messages: Message[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "assistant") {
      for (const part of msg.content) {
        if (part.type === "text") return part.text;
      }
    }
  }
  return "";
}

export function getResultOutput(result: SingleRunResult): string {
  if (isFailedResult(result)) {
    return (
      result.errorMessage ||
      result.stderr ||
      getFinalOutput(result.messages) ||
      "(no output)"
    );
  }
  return getFinalOutput(result.messages) || "(no output)";
}

export function truncateForModel(
  output: string,
  cap: number = PER_TASK_OUTPUT_CAP,
): string {
  const { text, omittedBytes } = truncateUtf8(output, cap);
  if (omittedBytes === 0) return output;
  return `${text}\n\n[Output truncated: ${omittedBytes} bytes omitted.]`;
}

function truncateInline(text: string, maxLen = 400): string {
  const trimmed = text.trim();
  return trimmed.length > maxLen ? `${trimmed.slice(0, maxLen)}...` : trimmed;
}

/**
 * Renders one run's full message history as a readable markdown transcript,
 * persisted alongside its `lifecycle.ts` status for later inspection
 * (`transcript.md`). Not truncated — this is the durable record, distinct
 * from the capped summaries surfaced back to the calling model.
 */
export function renderTranscriptMarkdown(result: SingleRunResult): string {
  const lines: string[] = [
    `# Subagent run: ${result.agent}`,
    "",
    `- runId: ${result.runId}`,
    `- model: ${result.model ?? "(unknown)"}`,
    `- exitCode: ${result.exitCode}`,
    result.stopReason ? `- stopReason: ${result.stopReason}` : undefined,
    "",
    "## Task",
    "",
    result.task,
    "",
    "## Transcript",
    "",
  ].filter((line): line is string => line !== undefined);

  for (const message of result.messages) {
    if (message.role === "assistant") {
      for (const part of message.content) {
        if (part.type === "text") {
          lines.push(part.text, "");
        } else if (part.type === "toolCall") {
          lines.push(
            `**Tool call: \`${part.name}\`**`,
            "",
            "```json",
            JSON.stringify(part.arguments, null, 2),
            "```",
            "",
          );
        }
      }
    } else if (message.role === "toolResult") {
      const text = message.content
        .filter((part) => part.type === "text")
        .map((part) => part.text)
        .join("\n");
      lines.push(
        `**Tool result${message.isError ? " (error)" : ""}: \`${message.toolName}\`**`,
        "",
        truncateInline(text, 2000),
        "",
      );
    }
  }

  if (result.errorMessage) lines.push("## Error", "", result.errorMessage, "");
  if (result.stderr.trim())
    lines.push("## stderr", "", "```", result.stderr.trim(), "```", "");

  return lines.join("\n");
}

export function formatParallelSummary(results: SingleRunResult[]): string {
  const successCount = results.filter((r) => !isFailedResult(r)).length;
  const summaries = results.map((r) => {
    const output = truncateForModel(getResultOutput(r));
    const status = isFailedResult(r)
      ? `failed${r.stopReason && r.stopReason !== "end" ? ` (${r.stopReason})` : ""}`
      : "completed";
    return `### [${r.agent}] ${status}\n\n${output}`;
  });
  return `Parallel: ${successCount}/${results.length} succeeded\n\n${summaries.join("\n\n---\n\n")}`;
}
