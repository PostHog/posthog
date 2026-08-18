// @vitest-environment node
// The S3 upload posts real multipart FormData, which jsdom's FormData
// polyfill cannot feed into undici's fetch.
import type { AuthService } from "@posthog/core/auth/auth";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { type QuickAskEvent, QuickAskService } from "./quick-ask";
import {
  REPLAY_ANSWER,
  REPLAY_FOLLOW_UP,
  REPLAY_FOLLOW_UP_ANSWER,
  REPLAY_FOLLOW_UP_PRELUDE,
  REPLAY_QUESTION,
  REPLAY_STRAY_ANSWER,
  type ReplayServer,
  startReplayServer,
} from "./replay-fixture";

/**
 * The whole transport against a real HTTP server replaying a production run's
 * stream: warm, task creation activating the warm run, the boot-time
 * description prompt whose turn must be skipped, a mid-answer stream rotation
 * resumed via Last-Event-ID, and a follow-up over the command relay.
 */

function authFor(origin: string): AuthService {
  return {
    getValidAccessToken: async () => ({ accessToken: "t", apiHost: origin }),
    getState: () => ({ currentProjectId: 2 }),
    authenticatedFetch: (
      fetchImpl: typeof fetch,
      url: string,
      init: RequestInit,
    ) => fetchImpl(url, init),
  } as unknown as AuthService;
}

async function collect(
  service: QuickAskService,
  question: string,
  conversationId?: string,
  attachments?: { name: string; base64: string; mimeType: string }[],
): Promise<QuickAskEvent[]> {
  const events: QuickAskEvent[] = [];
  for await (const event of service.ask({
    question,
    conversationId,
    attachments,
  })) {
    events.push(event);
  }
  return events;
}

describe("quick-ask against a replayed production stream", () => {
  let server: ReplayServer;
  let service: QuickAskService;

  beforeEach(async () => {
    server = await startReplayServer();
    service = new QuickAskService(authFor(server.origin));
  });

  afterEach(async () => {
    await server.close();
  });

  it("warms, asks, and renders only its own turn's answer", async () => {
    await service.warm();
    const events = await collect(service, REPLAY_QUESTION);

    const finalText = events.findLast((event) => event.type === "text");
    expect(finalText).toEqual({
      type: "text",
      id: "turn-1",
      content: REPLAY_ANSWER,
      complete: true,
    });
    expect(events.at(-1)).toEqual({ type: "done" });
    expect(events.some((event) => event.type === "error")).toBe(false);
    // The description turn's output stays out of the panel.
    const allText = events
      .filter((event) => event.type === "text")
      .map((event) => event.content)
      .join("");
    expect(allText).not.toContain(REPLAY_STRAY_ANSWER);
    // Its tool activity stays out too; only the answering turn's shows.
    const reasoning = events.filter((event) => event.type === "reasoning");
    expect(reasoning).toContainEqual({
      type: "reasoning",
      content: "Running execute-sql…",
    });

    // The rotation forced a resume with the cursor.
    expect(server.streamRequests.length).toBeGreaterThanOrEqual(2);
    expect(server.streamRequests[1].lastEventId).toMatch(/^\d+-0$/);

    // The create call opted into warm reuse and carried the message.
    const create = server.requests.find((r) => r.path.endsWith("/tasks/"));
    const body = create?.body as Record<string, unknown>;
    expect(body.description).toBe(REPLAY_QUESTION);
    expect(body).toHaveProperty("branch", null);
    expect(String(body.pending_user_message)).toContain(
      "<posthog_trusted_context>",
    );
  });

  it("continues the thread with a follow-up over the command relay", async () => {
    const first = await collect(service, REPLAY_QUESTION);
    const conversation = first.find((event) => event.type === "conversation");
    if (conversation?.type !== "conversation") throw new Error("no thread id");

    const events = await collect(
      service,
      REPLAY_FOLLOW_UP,
      conversation.conversationId,
    );
    // Text on both sides of the tool call arrives as two segments.
    expect(events).toContainEqual({
      type: "text",
      id: "turn-2",
      content: REPLAY_FOLLOW_UP_PRELUDE,
      complete: true,
    });
    const finalText = events.findLast((event) => event.type === "text");
    expect(finalText).toEqual({
      type: "text",
      id: "turn-2.2",
      content: REPLAY_FOLLOW_UP_ANSWER,
      complete: true,
    });
    expect(events.at(-1)).toEqual({ type: "done" });

    const command = server.requests.find((r) => r.path.endsWith("/command/"));
    expect((command?.body as { method?: string }).method).toBe("user_message");
  });

  it("uploads a screenshot and references it on the follow-up", async () => {
    const first = await collect(service, REPLAY_QUESTION);
    const conversation = first.find((event) => event.type === "conversation");
    if (conversation?.type !== "conversation") throw new Error("no thread id");

    const events = await collect(
      service,
      REPLAY_FOLLOW_UP,
      conversation.conversationId,
      [{ name: "screenshot.png", base64: btoa("png"), mimeType: "image/png" }],
    );
    expect(events.at(-1)).toEqual({ type: "done" });

    const prepare = server.requests.find((r) =>
      r.path.endsWith("/prepare_upload/"),
    );
    expect(prepare?.path).toContain("/runs/run-1/artifacts/");
    const upload = server.requests.find((r) => r.path.endsWith("/s3-upload/"));
    expect(String(upload?.body)).toContain("screenshot.png");
    const command = server.requests.find((r) => r.path.endsWith("/command/"));
    expect(
      (command?.body as { params?: { artifact_ids?: string[] } }).params
        ?.artifact_ids,
    ).toEqual(["art-1"]);
  });
});
