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
  "awaiting_input",
  "artifact_created",
  "artifact_revised",
  "canvas_created",
  "pr_created",
  "pr_merged",
  "pr_closed",
  "message_forwarded",
] as const;

export type ActivityEventKind = (typeof ACTIVITY_EVENTS)[number];

const ACTIVITY_EVENT_SET: ReadonlySet<string> = new Set(ACTIVITY_EVENTS);

export interface RunStartedPayload {
  runId: string;
  environment: string;
  branch: string;
}

export interface RunFailedPayload {
  runId: string;
  errorSummary: string;
}

export interface AwaitingInputPayload {
  runId: string;
}

export interface ArtifactPayload {
  artifactId: string;
  name: string;
  artifactType: string;
  version: number;
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

export type ActivityEvent =
  | { kind: "run_started"; payload: RunStartedPayload }
  | { kind: "run_failed"; payload: RunFailedPayload }
  | { kind: "awaiting_input"; payload: AwaitingInputPayload }
  | { kind: "artifact_created"; payload: ArtifactPayload }
  | { kind: "artifact_revised"; payload: ArtifactPayload }
  | { kind: "canvas_created"; payload: CanvasCreatedPayload }
  | { kind: "pr_created"; payload: PrPayload }
  | { kind: "pr_merged"; payload: PrPayload }
  | { kind: "pr_closed"; payload: PrPayload }
  | { kind: "message_forwarded"; payload: MessageForwardedPayload };

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
  };
}

export function isActivityEventKind(event: string): event is ActivityEventKind {
  return ACTIVITY_EVENT_SET.has(event);
}

/**
 * The typed event a thread message carries, or `null` when the message isn't one this
 * client renders — a human message, an older event, or one added after this release.
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
    case "awaiting_input":
      return { kind: event, payload: { runId: str(payload.run_id) } };
    case "artifact_created":
    case "artifact_revised":
      return { kind: event, payload: artifactPayload(payload) };
    case "canvas_created":
      return {
        kind: event,
        payload: {
          name: str(payload.canvas_name, "Canvas"),
          url: optionalStr(payload.canvas_url),
        },
      };
    case "pr_created":
    case "pr_merged":
    case "pr_closed": {
      const parsed = prPayload(payload);
      // A PR row with no url can't be labelled or opened, so it isn't a row.
      return parsed.prUrl ? { kind: event, payload: parsed } : null;
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

/** "owner/repo#12" when the event knows both, else the bare url. */
export function prLabel(payload: PrPayload): string {
  if (payload.repository && payload.prNumber !== null) {
    return `${payload.repository}#${payload.prNumber}`;
  }
  return payload.prUrl;
}
