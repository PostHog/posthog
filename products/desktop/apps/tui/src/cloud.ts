import { appendFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { createCloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import type { RootLogger, ScopedLogger } from "@posthog/di/logger";
import type { IAnalytics } from "@posthog/platform/analytics";
import { TRANSCRIPT_TAIL_WINDOW } from "@posthog/shared";
import { currentRepository, PiChats } from "./chats";
import { type PiCommand, type PiControl, piControl } from "./models";
import { CloudRuns } from "./runs";

export const LOG_PATH = join(tmpdir(), "posthog-tui.log");

interface TokenSource {
  getAccessToken(): Promise<string>;
  refreshAccessToken(): Promise<string>;
}

export function authenticatedFetch(
  auth: TokenSource,
  fetch: typeof globalThis.fetch = globalThis.fetch,
): (url: string, init?: RequestInit) => Promise<Response> {
  const send = (url: string, init: RequestInit | undefined, token: string) => {
    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return fetch(url, { ...init, headers });
  };
  return async (url, init) => {
    const response = await send(url, init, await auth.getAccessToken());
    if (response.status !== 401) return response;
    return send(url, init, await auth.refreshAccessToken());
  };
}

// Ink owns the screen, so logs go to a file.
function fileLogger(scope: string): ScopedLogger {
  const write =
    (level: string) =>
    (...args: unknown[]): void =>
      appendFileSync(
        LOG_PATH,
        `${new Date().toISOString()} ${level} [${scope}] ${args
          .map((arg) => (typeof arg === "string" ? arg : JSON.stringify(arg)))
          .join(" ")}\n`,
      );
  return {
    debug: write("debug"),
    info: write("info"),
    warn: write("warn"),
    error: write("error"),
  };
}

const logger: RootLogger = { ...fileLogger("tui"), scope: fileLogger };

const noAnalytics: IAnalytics = {
  initialize: () => {},
  track: () => {},
  identify: () => {},
  setCurrentUserId: () => {},
  getCurrentUserId: () => null,
  getOrCreateSessionId: () => "posthog-tui",
  resetUser: () => {},
  captureException: () => {},
  flush: async () => {},
  shutdown: async () => {},
};

export function createCloud(
  auth: TokenSource & { apiHost: string },
  api: PostHogAPIClient,
): {
  runs: CloudRuns;
  chats: PiChats;
  control: (taskId: string, runId: string) => PiControl;
} {
  let teamId: Promise<number> | null = null;
  const context = async () => {
    teamId ??= api.getCurrentUser().then(
      (user) => user.team.id,
      (error: unknown) => {
        teamId = null;
        throw error;
      },
    );
    return { apiHost: auth.apiHost, teamId: await teamId };
  };
  const engine = createCloudTaskEngine({
    auth: {
      authenticatedFetch: authenticatedFetch(auth),
      getCloudContext: context,
    },
    analytics: noAnalytics,
    logger,
    transcriptTailWindow: TRANSCRIPT_TAIL_WINDOW,
  });
  const runs = new CloudRuns(engine, context, (taskId, runId, options) =>
    api.getTaskRunSessionLogsPage(taskId, runId, options),
  );
  const sendMessage = async (
    taskId: string,
    runId: string,
    content: string,
  ) => {
    const result = await engine.sendCommand({
      taskId,
      runId,
      ...(await context()),
      method: "user_message",
      params: { content, artifact_ids: [], steer: false },
    });
    if (!result.success)
      throw new Error(result.error ?? "Couldn't send the message");
  };
  const sendPi: PiCommand = async (input) =>
    engine.sendCommand({ ...input, ...(await context()) });
  return {
    runs,
    chats: new PiChats(api, sendMessage, currentRepository()),
    control: (taskId, runId) => piControl(sendPi, taskId, runId),
  };
}
