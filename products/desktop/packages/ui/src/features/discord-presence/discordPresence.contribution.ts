import type { Contribution } from "@posthog/di/contribution";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable } from "inversify";
import { subscribeToRouterResolved } from "../../router/navigationBridge";
import { getAppViewSnapshot } from "../../router/useAppView";
import { sessionStoreSetters, useSessionStore } from "../sessions/sessionStore";
import { getCachedTask } from "../tasks/queries";
import {
  DISCORD_PRESENCE_CLIENT,
  type DiscordPresenceClient,
  type PresenceIntent,
} from "./identifiers";

/**
 * Keeps Discord Rich Presence in sync with what the user is doing. "What the
 * user is looking at" is genuinely renderer-owned (the current route + session),
 * so we compute it here and hand a small payload to the host service, which owns
 * the connection and the privacy-aware formatting. Started once at boot.
 */
@injectable()
export class DiscordPresenceContribution implements Contribution {
  private readonly log: ScopedLogger;
  // Last payload we sent, to avoid spamming the host with no-op updates as the
  // route/session churn. The host service additionally rate-limits before it
  // reaches Discord.
  private lastSent = "";

  constructor(
    @inject(DISCORD_PRESENCE_CLIENT)
    private readonly client: DiscordPresenceClient,
    @inject(ROOT_LOGGER) logger: RootLogger,
  ) {
    this.log = logger.scope("discord-presence");
  }

  start(): void {
    this.push();
    subscribeToRouterResolved(() => this.push());
    useSessionStore.subscribe(() => this.push());
  }

  private computeIntent(): PresenceIntent {
    const view = getAppViewSnapshot();
    const taskId = view.type === "task-detail" ? view.taskId : undefined;
    // The router only carries the taskId; resolve title/repo from cached tasks.
    const task = taskId ? getCachedTask(taskId) : undefined;

    let agentRunning = false;
    if (taskId) {
      const session = sessionStoreSetters.getSessionByTaskId(taskId);
      agentRunning = session?.isPromptPending ?? false;
    }

    return {
      hasActiveTask: Boolean(taskId),
      taskTitle: task?.title ?? null,
      repoName: task?.repository ?? null,
      agentRunning,
    };
  }

  private push(): void {
    const intent = this.computeIntent();
    const key = JSON.stringify(intent);
    if (key === this.lastSent) return;
    this.lastSent = key;
    this.client.setActivity(intent).catch((error) => {
      this.log.warn("Failed to update Discord presence", { error });
    });
  }
}
