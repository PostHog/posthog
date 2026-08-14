import { readAgentToolName, readMcpToolDescriptor } from "@posthog/shared";
import { getContentText } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import type { ToolCall } from "@posthog/ui/features/sessions/types";

const UPLOAD_ARTIFACT_TOOL = "upload_artifact";

/** The agent's `upload_artifact` call, which delivers a file to the artifacts panel. */
export function isUploadArtifactCall(meta: unknown): boolean {
  return readMcpToolDescriptor(meta)?.tool === UPLOAD_ARTIFACT_TOOL;
}

/** The download name the upload will land under: the given name, else the file's own. */
export function readUploadedArtifactName(rawInput: unknown): string | null {
  if (!rawInput || typeof rawInput !== "object") return null;
  const input = rawInput as { name?: unknown; path?: unknown };
  if (typeof input.name === "string" && input.name.trim()) {
    return input.name.trim();
  }
  if (typeof input.path === "string" && input.path.trim()) {
    const segments = input.path.trim().split(/[\\/]/).filter(Boolean);
    return segments.at(-1) ?? null;
  }
  return null;
}

const PR_URL_PATTERN =
  /https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/pull\/\d+(?![\w/])/;
// No leading word boundary on the second alternative: an MCP tool name arrives
// as `mcp__github__create_pull_request`, where the underscore is a word char.
const PR_CREATION_PATTERN = /\bpr\s+create\b|create[_-]?pull[_-]?request/i;

function toolCallOutputText(toolCall: ToolCall): string {
  const content = getContentText(toolCall.content) ?? "";
  const raw = toolCall.rawOutput;
  return typeof raw === "string" ? `${content}\n${raw}` : content;
}

/**
 * The pull request a tool call just opened, or null.
 *
 * Gated on the call looking like a creation (`gh pr create`, an MCP
 * create-pull-request tool) rather than on the URL alone: a run that reads or
 * comments on someone else's PR prints the same URL, and that is not something
 * the run produced.
 */
export function readCreatedPrUrl(toolCall: ToolCall): string | null {
  if (toolCall.status !== "completed") return null;

  const intent = [
    readAgentToolName(toolCall._meta) ?? "",
    toolCall.rawInput ? JSON.stringify(toolCall.rawInput) : "",
  ].join(" ");
  if (!PR_CREATION_PATTERN.test(intent)) return null;

  return PR_URL_PATTERN.exec(toolCallOutputText(toolCall))?.[0] ?? null;
}

/** Whether a tool call draws an artifact card, which never folds into a tool group. */
export function hasInlineArtifact(toolCall: ToolCall): boolean {
  return (
    isUploadArtifactCall(toolCall._meta) || readCreatedPrUrl(toolCall) !== null
  );
}
