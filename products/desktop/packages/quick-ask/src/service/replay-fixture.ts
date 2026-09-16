import http from "node:http";
import type { AddressInfo } from "node:net";
import { PANEL_STEERING } from "./steering";

/**
 * Replay of a production quick-ask run's stream, for the integration test and
 * the panel end-to-end script (`scripts/quick-ask-e2e.mts`). The
 * frame ordering is the part that matters and is taken from a real run: the
 * workflow prompts the task description at boot, prompt queueing logs the
 * panel's prompt before that turn completes, and the answer arrives in the
 * second turn. Frame contents are invented.
 */

export const REPLAY_QUESTION = "How many signups this week?";
export const REPLAY_FIRST_TURN_CONTENT = `${REPLAY_QUESTION}\n\n${PANEL_STEERING}`;
export const REPLAY_FOLLOW_UP = "And the week before?";

export const REPLAY_ANSWER = [
  "Signups held steady this week. The <hogql label=\"Tuesday spike\">SELECT count() FROM events WHERE event = 'signed_up' AND toDayOfWeek(timestamp) = 2</hogql> matches the launch email.",
  "",
  '<hogql display="block" title="Signups per day, last 7 days">SELECT toDate(timestamp) AS day, count() FROM events WHERE event = \'signed_up\' GROUP BY day ORDER BY day</hogql>',
].join("\n");
export const REPLAY_FOLLOW_UP_PRELUDE = "Comparing against last week.";
export const REPLAY_FOLLOW_UP_ANSWER = "About 1,100, a touch below this week.";
/** Output of the description turn; the panel must never show it. */
export const REPLAY_STRAY_ANSWER = "Looking into signups now.";

function notification(method: string, params: unknown): object {
  return {
    type: "notification",
    notification: { jsonrpc: "2.0", method, params },
  };
}

function console_(message: string): object {
  return notification("_posthog/console", { level: "debug", message });
}

function sessionUpdate(update: object): object {
  return notification("session/update", { sessionId: "s1", update });
}

function agentText(text: string): object {
  return sessionUpdate({
    sessionUpdate: "agent_message_chunk",
    content: { type: "text", text },
  });
}

function prompt(text: string): object {
  return notification("session/prompt", {
    sessionId: "s1",
    prompt: [{ type: "text", text }],
  });
}

const TURN_COMPLETE = notification("_posthog/turn_complete", {
  sessionId: "s1",
  stopReason: "end_turn",
});

/** First-turn frames, in the production order. */
export const REPLAY_FRAMES: object[] = [
  { type: "task_run_state", status: "queued" },
  console_("Setting up sandbox"),
  console_("Sandbox provisioned"),
  { type: "task_run_state", status: "in_progress" },
  notification("initialize", { protocolVersion: 1 }),
  notification("session/new", { cwd: "/tmp/workspace" }),
  notification("_posthog/run_started", { sessionId: "s1" }),
  sessionUpdate({
    sessionUpdate: "available_commands_update",
    availableCommands: [],
  }),
  // The workflow prompts the task description; the panel's prompt is queued
  // behind it and logged before the first turn completes.
  prompt(REPLAY_QUESTION),
  prompt(REPLAY_FIRST_TURN_CONTENT),
  sessionUpdate({
    sessionUpdate: "tool_call",
    toolCallId: "t0",
    title: "execute-sql",
  }),
  sessionUpdate({
    sessionUpdate: "tool_call_update",
    toolCallId: "t0",
    status: "completed",
  }),
  agentText(REPLAY_STRAY_ANSWER),
  TURN_COMPLETE,
  sessionUpdate({
    sessionUpdate: "agent_thought_chunk",
    content: { type: "text", text: "Charting signups by day" },
  }),
  sessionUpdate({
    sessionUpdate: "tool_call",
    toolCallId: "t1",
    title: "execute-sql",
  }),
  agentText(REPLAY_ANSWER.slice(0, 40)),
  agentText(REPLAY_ANSWER.slice(40)),
  TURN_COMPLETE,
];

/** Frame index after which the first stream connection rotates. */
export const REPLAY_ROTATE_AFTER = 15;

/**
 * Follow-up turn frames, appended once the follow-up command arrives. Text
 * lands on both sides of the tool call, so the turn produces two segments.
 */
export const REPLAY_FOLLOW_UP_FRAMES: object[] = [
  prompt(REPLAY_FOLLOW_UP),
  agentText(REPLAY_FOLLOW_UP_PRELUDE),
  sessionUpdate({
    sessionUpdate: "tool_call",
    toolCallId: "t2",
    title: "execute-sql",
  }),
  agentText(REPLAY_FOLLOW_UP_ANSWER),
  TURN_COMPLETE,
];

export interface ReplayServer {
  origin: string;
  /** Request bodies seen, keyed by route suffix. */
  requests: { path: string; body: unknown }[];
  streamRequests: { lastEventId: string | null }[];
  close(): Promise<void>;
}

function sseFrame(id: number, data: object): string {
  return `id: ${id}-0\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * Serves the tasks API surface quick-ask speaks: warm, create (returning an
 * activated run), the command relay, and the run's SSE stream. The stream
 * rotates once mid-answer, so resuming with `Last-Event-ID` is exercised on
 * every run of the fixture. Follow-up frames start streaming once a
 * `user_message` command arrives.
 */
export async function startReplayServer(): Promise<ReplayServer> {
  const requests: { path: string; body: unknown }[] = [];
  const streamRequests: { lastEventId: string | null }[] = [];
  let followUpRequested = false;

  const allFrames = (): object[] =>
    followUpRequested
      ? [...REPLAY_FRAMES, ...REPLAY_FOLLOW_UP_FRAMES]
      : REPLAY_FRAMES;

  const server = http.createServer((request, response) => {
    const url = request.url ?? "";
    let raw = "";
    request.on("data", (chunk) => {
      raw += chunk;
    });
    request.on("end", () => {
      // The presigned S3 upload posts multipart form data, not JSON.
      let body: unknown = null;
      try {
        body = raw ? JSON.parse(raw) : null;
      } catch {
        body = raw;
      }
      requests.push({ path: url, body });

      if (url.endsWith("/prepare_upload/")) {
        const artifacts = (
          (body as { artifacts?: object[] } | null)?.artifacts ?? []
        ).map((artifact, index) => ({
          ...artifact,
          id: `art-${index + 1}`,
          presigned_post: {
            url: `http://${request.headers.host}/s3-upload/`,
            fields: { key: `uploads/art-${index + 1}` },
          },
        }));
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ artifacts }));
        return;
      }
      if (url.endsWith("/s3-upload/")) {
        response.writeHead(204);
        response.end();
        return;
      }
      if (url.endsWith("/finalize_upload/")) {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(
          JSON.stringify({
            artifacts: (body as { artifacts?: object[] }).artifacts ?? [],
          }),
        );
        return;
      }

      if (url.endsWith("/tasks/warm/")) {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ task_id: "task-1", run_id: "run-1" }));
        return;
      }
      if (url.endsWith("/tasks/")) {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(
          JSON.stringify({
            id: "task-1",
            latest_run: { id: "run-1", status: "in_progress" },
          }),
        );
        return;
      }
      if (url.endsWith("/command/")) {
        const method = (body as { method?: string } | null)?.method;
        if (method === "user_message") {
          followUpRequested = true;
        }
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ success: true }));
        return;
      }
      if (url.includes("/stream/")) {
        const lastEventId = request.headers["last-event-id"];
        const cursor =
          typeof lastEventId === "string"
            ? Number.parseInt(lastEventId, 10)
            : -1;
        streamRequests.push({
          lastEventId: typeof lastEventId === "string" ? lastEventId : null,
        });
        response.writeHead(200, { "Content-Type": "text/event-stream" });

        const frames = allFrames();
        // The first connection rotates mid-answer; resumed connections send
        // the rest and stay open (like the real stream between turns).
        const rotate = cursor < 0 && frames.length > REPLAY_ROTATE_AFTER;
        const end = rotate ? REPLAY_ROTATE_AFTER + 1 : frames.length;
        for (let index = cursor + 1; index < end; index++) {
          response.write(sseFrame(index, frames[index]));
        }
        if (rotate) {
          response.write('event: end\ndata: {"type":"rotated"}\n\n');
          response.end();
          return;
        }
        const poll = setInterval(() => {
          const grown = allFrames();
          for (let index = end; index < grown.length; index++) {
            response.write(sseFrame(index, grown[index]));
          }
          if (grown.length > end) {
            clearInterval(poll);
            response.end();
          }
        }, 20);
        request.on("close", () => clearInterval(poll));
        return;
      }
      response.writeHead(404);
      response.end();
    });
  });

  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    origin: `http://127.0.0.1:${port}`,
    requests,
    streamRequests,
    close: () =>
      new Promise((resolve) => {
        server.closeAllConnections();
        server.close(() => resolve());
      }),
  };
}
