/**
 * Minimal shape of a task thread message the timeline needs — structurally
 * satisfied by `TaskThreadMessage` without coupling to the full domain type.
 */
export interface ThreadMessageLike {
  id: string;
  content: string;
  created_at: string;
  author_kind?: "human" | "system" | "agent";
  event?: string;
  payload?: Record<string, unknown>;
}

export type ThreadArtifact =
  | { kind: "canvas"; name: string; url: string | null }
  | { kind: "pr"; url: string };

export type ThreadTimelineRow<T extends ThreadMessageLike = ThreadMessageLike> =
  | { kind: "human"; timestamp: number; message: T }
  | {
      kind: "artifact";
      timestamp: number;
      message: T;
      artifact: ThreadArtifact;
    };

function parsedTimestamp(timestamp: string): number {
  const parsed = Date.parse(timestamp);
  return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER;
}

/**
 * The artifact an agent-authored thread message announces, or `null` when the
 * message isn't an artifact announcement (e.g. `turn_complete`).
 */
export function threadMessageArtifact(
  message: ThreadMessageLike,
): ThreadArtifact | null {
  const payload = message.payload ?? {};
  if (message.event === "canvas_created") {
    const name =
      typeof payload.canvas_name === "string" && payload.canvas_name.trim()
        ? payload.canvas_name
        : "Canvas";
    const url =
      typeof payload.canvas_url === "string" ? payload.canvas_url : null;
    return { kind: "canvas", name, url };
  }
  if (message.event === "pr_created") {
    const url = typeof payload.pr_url === "string" ? payload.pr_url : null;
    return url ? { kind: "pr", url } : null;
  }
  return null;
}

/**
 * The thread is a human-to-human surface: only human messages and the
 * artifacts the agent produced (canvases, pull requests) appear. Agent turn
 * messages and forwarded prompts are omitted.
 */
export function buildThreadTimeline<T extends ThreadMessageLike>(
  messages: T[],
): ThreadTimelineRow<T>[] {
  const rows: ThreadTimelineRow<T>[] = [];
  for (const message of messages) {
    const timestamp = parsedTimestamp(message.created_at);
    const artifact = threadMessageArtifact(message);
    if (artifact) {
      rows.push({ kind: "artifact", timestamp, message, artifact });
    } else if ((message.author_kind ?? "human") === "human") {
      rows.push({ kind: "human", timestamp, message });
    }
  }
  return rows.sort((left, right) => left.timestamp - right.timestamp);
}

export type ThreadAgentPhase = "active" | "needs_input" | "error";

export interface ThreadAgentStatus {
  phase: ThreadAgentPhase;
  label: string;
}

const AGENT_MENTION_PATTERN = /(^|\s)@agent\b/i;

export function hasAgentMention(content: string): boolean {
  return AGENT_MENTION_PATTERN.test(content);
}

export function deriveThreadAgentStatus({
  hasActivity = false,
  hasError = false,
  cloudStatus,
  errorTitle,
  pendingPermissionCount = 0,
  isPromptPending = false,
  isInitializing = false,
}: {
  hasActivity?: boolean;
  hasError?: boolean;
  cloudStatus?: string | null;
  errorTitle?: string | null;
  pendingPermissionCount?: number;
  isPromptPending?: boolean;
  isInitializing?: boolean;
}): ThreadAgentStatus | null {
  if (!hasActivity) return null;
  if (hasError || cloudStatus === "failed") {
    return { phase: "error", label: errorTitle ?? "Failed" };
  }
  if (pendingPermissionCount > 0) {
    return { phase: "needs_input", label: "Needs input" };
  }
  if (isPromptPending || isInitializing) {
    return { phase: "active", label: "Working…" };
  }
  return null;
}

export function shouldSuspendThreadSession({
  isCloud,
  hasRun,
  hasSession,
}: {
  isCloud: boolean;
  hasRun: boolean;
  hasSession: boolean;
}): boolean {
  return !isCloud && !hasRun && !hasSession;
}
