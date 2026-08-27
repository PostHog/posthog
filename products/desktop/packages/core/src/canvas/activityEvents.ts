/**
 * The vocabulary of server-emitted task events the activity timeline renders.
 *
 * Mirrors `TaskActivityEvent` in `products/tasks/backend/models.py`; a test asserts the
 * two lists match. `parseActivityEvent` returns `null` for anything it doesn't know, which
 * is what lets the backend emit a new event before this client can draw it.
 */

export const ACTIVITY_EVENTS = [
  "run_started",
  "run_failed",
  "commits_pushed",
  "awaiting_input",
  "artifact_created",
  "artifact_revised",
  "canvas_created",
  "comment_added",
  "comment_state_changed",
  "pr_created",
  "pr_merged",
  "pr_closed",
  "message_forwarded",
  "task_handed_off",
] as const;

export type ActivityEventKind = (typeof ACTIVITY_EVENTS)[number];

const ACTIVITY_EVENT_SET: ReadonlySet<string> = new Set(ACTIVITY_EVENTS);

const RUN_ARTIFACT_TYPES_WITHOUT_TIMELINE_EVENTS: ReadonlySet<string> = new Set(
  [
    "plan",
    "context",
    "reference",
    "artifact",
    "tree_snapshot",
    "user_attachment",
    "skill_bundle",
  ],
);

export interface RunStartedPayload {
  runId: string;
  environment: string;
  branch: string;
}

export interface RunFailedPayload {
  runId: string;
  errorSummary: string;
}

export interface CommitsPushedPayload {
  runId: string;
  branch: string;
  repository: string | null;
  commits: { sha: string; subject: string; url: string | null }[];
  /** How many the push carried; `commits` is capped, so this can be larger. */
  total: number;
}

export interface AwaitingInputPayload {
  runId: string;
}

export interface ArtifactPayload {
  artifactId: string;
  name: string;
  artifactType: string;
  version: number;
  /** Names the run whose artifact tab can open this; null on rows that predate it. */
  runId: string | null;
  referenceType: string | null;
  objectKind: string | null;
}

export interface CanvasCreatedPayload {
  name: string;
  url: string | null;
}

export interface PrPayload {
  prUrl: string;
  repository: string | null;
  prNumber: number | null;
  actor: string | null;
}

export interface MessageForwardedPayload {
  messageId: string;
  runId: string;
}

export interface TaskHandedOffPayload {
  fromUserId: number | null;
  toUserId: number;
  /** Rendered names, so the row can read without a member lookup. */
  fromDisplayName: string | null;
  toDisplayName: string;
}

/** Identity only: the thread body, quote, and replies are fetched when the row opens. */
export interface CommentEventPayload {
  commentId: string;
  rootCommentId: string;
  scope: string;
  itemId: string | null;
  /** Display name of the commented artifact; null on the task's own scope. */
  targetName: string | null;
}

export interface CommentStateChangedPayload extends CommentEventPayload {
  state: "resolved" | "open";
}

export type ActivityEvent =
  | { kind: "run_started"; payload: RunStartedPayload }
  | { kind: "run_failed"; payload: RunFailedPayload }
  | { kind: "commits_pushed"; payload: CommitsPushedPayload }
  | { kind: "awaiting_input"; payload: AwaitingInputPayload }
  | { kind: "artifact_created"; payload: ArtifactPayload }
  | { kind: "artifact_revised"; payload: ArtifactPayload }
  | { kind: "canvas_created"; payload: CanvasCreatedPayload }
  | { kind: "comment_added"; payload: CommentEventPayload }
  | { kind: "comment_state_changed"; payload: CommentStateChangedPayload }
  | { kind: "pr_created"; payload: PrPayload }
  | { kind: "pr_merged"; payload: PrPayload }
  | { kind: "pr_closed"; payload: PrPayload }
  | { kind: "message_forwarded"; payload: MessageForwardedPayload }
  | { kind: "task_handed_off"; payload: TaskHandedOffPayload };

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function optionalStr(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function prPayload(payload: Record<string, unknown>): PrPayload {
  return {
    prUrl: str(payload.pr_url),
    repository: optionalStr(payload.repository),
    prNumber: typeof payload.pr_number === "number" ? payload.pr_number : null,
    actor: optionalStr(payload.actor),
  };
}

function artifactPayload(payload: Record<string, unknown>): ArtifactPayload {
  return {
    artifactId: str(payload.artifact_id),
    name: str(payload.name, "Artifact"),
    artifactType: str(payload.artifact_type),
    version: num(payload.version, 1),
    runId: optionalStr(payload.run_id),
    referenceType: optionalStr(payload.reference_type),
    objectKind: optionalStr(payload.object_kind),
  };
}

export function isActivityEventKind(event: string): event is ActivityEventKind {
  return ACTIVITY_EVENT_SET.has(event);
}

/**
 * The typed event a thread message carries, or `null` when the message isn't one this
 * client renders: a human message, an older event, or one added after this release.
 */
export function parseActivityEvent(message: {
  event?: string;
  payload?: Record<string, unknown>;
}): ActivityEvent | null {
  const event = message.event ?? "";
  if (!isActivityEventKind(event)) return null;
  const payload = message.payload ?? {};
  switch (event) {
    case "run_started":
      return {
        kind: event,
        payload: {
          runId: str(payload.run_id),
          environment: str(payload.environment),
          branch: str(payload.branch),
        },
      };
    case "run_failed":
      return {
        kind: event,
        payload: {
          runId: str(payload.run_id),
          errorSummary: str(payload.error_summary),
        },
      };
    case "commits_pushed": {
      const raw = Array.isArray(payload.commits) ? payload.commits : [];
      const commits = raw.flatMap((entry) => {
        if (typeof entry !== "object" || entry === null) return [];
        const commit = entry as Record<string, unknown>;
        const sha = str(commit.sha);
        return sha
          ? [
              {
                sha,
                subject: str(commit.subject),
                url: optionalStr(commit.url),
              },
            ]
          : [];
      });
      // A push with no readable commit can't be drawn, so it isn't a row.
      return commits.length
        ? {
            kind: event,
            payload: {
              runId: str(payload.run_id),
              branch: str(payload.branch),
              repository: optionalStr(payload.repository),
              commits,
              total: num(payload.total, commits.length),
            },
          }
        : null;
    }
    case "awaiting_input":
      return { kind: event, payload: { runId: str(payload.run_id) } };
    case "artifact_created":
    case "artifact_revised": {
      const parsed = artifactPayload(payload);
      const visiblePostHogReference =
        parsed.artifactType === "reference" &&
        parsed.referenceType === "posthog_object";
      return RUN_ARTIFACT_TYPES_WITHOUT_TIMELINE_EVENTS.has(
        parsed.artifactType,
      ) && !visiblePostHogReference
        ? null
        : { kind: event, payload: parsed };
    }
    case "canvas_created":
      return {
        kind: event,
        payload: {
          name: str(payload.canvas_name, "Canvas"),
          url: optionalStr(payload.canvas_url),
        },
      };
    case "comment_added":
    case "comment_state_changed": {
      const rootCommentId = str(payload.root_comment_id);
      // A row with no thread to open or fetch cannot be drawn.
      if (!rootCommentId) return null;
      const base = {
        commentId: str(payload.comment_id),
        rootCommentId,
        scope: str(payload.scope),
        itemId: optionalStr(payload.item_id),
        targetName: optionalStr(payload.target_name),
      };
      if (event === "comment_added") {
        return { kind: event, payload: base };
      }
      const state = payload.state;
      return state === "resolved" || state === "open"
        ? { kind: event, payload: { ...base, state } }
        : null;
    }
    case "pr_created":
    case "pr_merged":
    case "pr_closed": {
      const parsed = prPayload(payload);
      // A PR row with no url can't be labelled or opened, so it isn't a row.
      return parsed.prUrl ? { kind: event, payload: parsed } : null;
    }
    case "task_handed_off": {
      // Older rows only carry user ids; a row with neither name can't say who
      // took over, so fall back to undrawn rather than label it wrong.
      const toDisplayName = optionalStr(payload.to_display_name);
      if (!toDisplayName) return null;
      return {
        kind: event,
        payload: {
          fromUserId:
            typeof payload.from_user_id === "number"
              ? payload.from_user_id
              : null,
          toUserId: num(payload.to_user_id, 0),
          fromDisplayName: optionalStr(payload.from_display_name),
          toDisplayName,
        },
      };
    }
    case "message_forwarded":
      return {
        kind: event,
        payload: {
          messageId: str(payload.message_id),
          runId: str(payload.run_id),
        },
      };
  }
}

const GITHUB_PR_URL = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/;

/** "owner/repo#12" when the event knows both, else read off the url, else the bare url. */
export function prLabel(payload: PrPayload): string {
  const repository = prRepository(payload);
  const number = payload.prNumber ?? prNumberFromUrl(payload.prUrl);
  if (repository && number !== null) return `${repository}#${number}`;
  return payload.prUrl;
}

/** The repository the event names, or the one its url points at. */
export function prRepository(payload: PrPayload): string | null {
  if (payload.repository) return payload.repository;
  const match = GITHUB_PR_URL.exec(payload.prUrl);
  return match ? `${match[1]}/${match[2]}` : null;
}

function prNumberFromUrl(url: string): number | null {
  const match = GITHUB_PR_URL.exec(url);
  return match ? Number(match[3]) : null;
}
