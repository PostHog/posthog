import { readMcpToolDescriptor } from "@posthog/shared";
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

/**
 * The whole MCP tool name, not a substring of it. `create_pull_request_review`
 * both contains this name and returns the url of the pull request it reviewed,
 * so a loose match reads someone else's PR back as this run's deliverable.
 */
const PR_CREATION_TOOL = /^create[_-]?pull[_-]?request$/i;

/**
 * `gh pr create` where a command can start: the beginning of the line, or after
 * a separator. Anywhere else it is being talked about rather than run, and the
 * body of a `gh pr comment` is the likeliest place for that.
 */
const GH_PR_CREATE_PATTERN = /(?:^|[\n;|&]\s*)gh\s+pr\s+create\b/;

/** The shell command a tool call ran, for the tools that carry one. */
function readCommand(rawInput: unknown): string {
  if (!rawInput || typeof rawInput !== "object") return "";
  const { command } = rawInput as { command?: unknown };
  if (typeof command === "string") return command;
  return Array.isArray(command) ? command.join(" ") : "";
}

function toolCallOutputText(toolCall: ToolCall): string {
  const content = getContentText(toolCall.content) ?? "";
  const raw = toolCall.rawOutput;
  return typeof raw === "string" ? `${content}\n${raw}` : content;
}

/**
 * Whether the call set out to open a pull request. Two ways in, because a shell
 * that opens one may itself be an MCP tool.
 */
function looksLikePrCreation(toolCall: ToolCall): boolean {
  const mcp = readMcpToolDescriptor(toolCall._meta);
  if (mcp && PR_CREATION_TOOL.test(mcp.tool)) return true;
  return GH_PR_CREATE_PATTERN.test(readCommand(toolCall.rawInput));
}

/**
 * The pull request a tool call just opened, or null.
 *
 * Gated on the call setting out to create one rather than on the url alone: a
 * run that reads, reviews or comments on someone else's PR prints the same url,
 * and that PR is not this run's deliverable.
 */
export function readCreatedPrUrl(toolCall: ToolCall): string | null {
  if (toolCall.status !== "completed") return null;
  if (!looksLikePrCreation(toolCall)) return null;

  return PR_URL_PATTERN.exec(toolCallOutputText(toolCall))?.[0] ?? null;
}

/** Whether a tool call draws an artifact card, which never folds into a tool group. */
export function hasInlineArtifact(toolCall: ToolCall): boolean {
  return (
    isUploadArtifactCall(toolCall._meta) || readCreatedPrUrl(toolCall) !== null
  );
}
