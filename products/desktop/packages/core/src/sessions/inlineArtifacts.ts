import { agentActionSchema } from "@posthog/core/agent-actions/schemas";
import { type AgentAction, readMcpToolDescriptor } from "@posthog/shared";

const UPLOAD_ARTIFACT_TOOL = "upload_artifact";
const SHOW_ACTIONS_TOOL = "show_actions";

/** The agent's `upload_artifact` call, which delivers a file to the artifacts panel. */
export function isUploadArtifactCall(meta: unknown): boolean {
  return readMcpToolDescriptor(meta)?.tool === UPLOAD_ARTIFACT_TOOL;
}

/** The agent's `show_actions` call, which offers the user buttons rather than a file. */
export function isShowActionsCall(meta: unknown): boolean {
  return readMcpToolDescriptor(meta)?.tool === SHOW_ACTIONS_TOOL;
}

/** One button a `show_actions` call is offering: its text, and the verb behind it. */
export interface ShowActionButton {
  label: string;
  action: AgentAction;
}

function readLabel(entry: unknown): string | null {
  if (!entry || typeof entry !== "object") return null;
  const { label } = entry as { label?: unknown };
  return typeof label === "string" && label.trim() ? label.trim() : null;
}

/**
 * The buttons to draw for a `show_actions` call. Every action is re-validated
 * against `agentActionSchema` — the same schema the host's dispatch accepts —
 * so an action that could never open anything is dropped instead of drawn as a
 * dead button. `label` is the card's own text and never reaches a link, so it
 * is read separately from the verb the schema declares.
 */
export function readShowActions(rawInput: unknown): ShowActionButton[] {
  if (!rawInput || typeof rawInput !== "object") return [];
  const { actions } = rawInput as { actions?: unknown };
  if (!Array.isArray(actions)) return [];

  const buttons: ShowActionButton[] = [];
  for (const entry of actions) {
    const parsed = agentActionSchema.safeParse(entry);
    const label = readLabel(entry);
    if (!parsed.success || !label) continue;
    buttons.push({ label, action: parsed.data });
  }
  return buttons;
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

// The whole MCP tool name, not a substring: `create_pull_request_review` also
// returns a PR url but did not create it, so a loose match reads someone else's
// PR back as this run's deliverable.
const PR_CREATION_TOOL = /^create[_-]?pull[_-]?request$/i;

// `gh pr create` where a command can start (line start or after a separator).
// Anywhere else it is being talked about — e.g. inside a `gh pr comment` body —
// rather than run.
const GH_PR_CREATE_PATTERN = /(?:^|[\n;|&]\s*)gh\s+pr\s+create\b/;

function readCommand(rawInput: unknown): string {
  if (!rawInput || typeof rawInput !== "object") return "";
  const { command } = rawInput as { command?: unknown };
  if (typeof command === "string") return command;
  return Array.isArray(command) ? command.join(" ") : "";
}

function looksLikePrCreation(meta: unknown, rawInput: unknown): boolean {
  const mcp = readMcpToolDescriptor(meta);
  if (mcp && PR_CREATION_TOOL.test(mcp.tool)) return true;
  return GH_PR_CREATE_PATTERN.test(readCommand(rawInput));
}

// Gated on the call setting out to create a PR rather than on the url alone, so
// a run that reads, reviews or comments on someone else's PR draws no card.
function matchesPrCreation(
  status: string | undefined,
  meta: unknown,
  rawInput: unknown,
): boolean {
  return status === "completed" && looksLikePrCreation(meta, rawInput);
}

/** A finished tool call, reduced to what PR-creation detection needs. */
export interface PrCreationCandidate {
  status: string | undefined;
  meta: unknown;
  rawInput: unknown;
  outputText: string;
}

/** The pull request a tool call just opened, or null. */
export function readCreatedPrUrl(call: PrCreationCandidate): string | null {
  if (!matchesPrCreation(call.status, call.meta, call.rawInput)) return null;
  return PR_URL_PATTERN.exec(call.outputText)?.[0] ?? null;
}

export type InlineArtifact = { kind: "upload" } | { kind: "pr"; url: string };

export interface InlineArtifactCandidate {
  status: string | undefined;
  meta: unknown;
  rawInput: unknown;
  /** Resolved only for a confirmed PR-creation call, so other rows never pay to build it. */
  getOutputText: () => string;
}

/** The deliverable a tool call produced — an uploaded file or an opened PR. */
export function detectInlineArtifact(
  call: InlineArtifactCandidate,
): InlineArtifact | null {
  if (isUploadArtifactCall(call.meta)) return { kind: "upload" };
  if (!matchesPrCreation(call.status, call.meta, call.rawInput)) return null;
  const url = PR_URL_PATTERN.exec(call.getOutputText())?.[0] ?? null;
  return url ? { kind: "pr", url } : null;
}
