import { TypedEventEmitter } from "@posthog/shared";
import { injectable, preDestroy } from "inversify";
import { logger } from "../../utils/logger";
import { settingsStore } from "../settingsStore";
import {
  getDiscordClientId,
  MIN_UPDATE_INTERVAL_MS,
  RECONNECT_INTERVAL_MS,
} from "./constants";
import { DiscordIpcClient } from "./discord-ipc";
import { buildActivity } from "./presence-format";
import {
  DiscordPresenceServiceEvent,
  type DiscordPresenceServiceEvents,
  type DiscordPresenceState,
  type PresenceIntent,
} from "./schemas";

const log = logger.scope("discord-presence");

const IDLE_INTENT: PresenceIntent = {
  hasActiveTask: false,
  taskTitle: null,
  repoName: null,
  agentRunning: false,
};

/**
 * Owns the Discord Rich Presence integration: the socket lifecycle,
 * reconnection, rate-limited activity updates, and the privacy-aware
 * formatting of what shows on the user's profile. The renderer only feeds it a
 * high-level {@link PresenceIntent}; all decisions live here so the same
 * behaviour ports to any future host.
 */
@injectable()
export class DiscordPresenceService extends TypedEventEmitter<DiscordPresenceServiceEvents> {
  private client: DiscordIpcClient | null = null;
  private enabled: boolean;
  private showTaskTitle: boolean;
  private showRepoName: boolean;
  private connected = false;
  private waiting = false;
  private intent: PresenceIntent = IDLE_INTENT;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private throttleTimer: NodeJS.Timeout | null = null;
  private lastUpdateAt = 0;
  private readonly startedAt = Date.now();
  private readonly clientId = getDiscordClientId();

  constructor() {
    super();
    this.enabled = settingsStore.get("discordPresenceEnabled", false);
    this.showTaskTitle = settingsStore.get(
      "discordPresenceShowTaskTitle",
      false,
    );
    this.showRepoName = settingsStore.get("discordPresenceShowRepoName", false);
    if (this.enabled) this.connect();
  }

  getState(): DiscordPresenceState {
    return {
      enabled: this.enabled,
      connected: this.connected,
      configured: this.clientId.length > 0,
      showTaskTitle: this.showTaskTitle,
      showRepoName: this.showRepoName,
    };
  }

  setEnabled(enabled: boolean): void {
    if (this.enabled === enabled) return;
    log.info("setEnabled", { enabled });
    this.enabled = enabled;
    settingsStore.set("discordPresenceEnabled", enabled);
    if (enabled) {
      this.connect();
    } else {
      this.disconnect();
    }
    this.emitStatus();
  }

  setShowTaskTitle(value: boolean): void {
    if (this.showTaskTitle === value) return;
    this.showTaskTitle = value;
    settingsStore.set("discordPresenceShowTaskTitle", value);
    this.render();
    this.emitStatus();
  }

  setShowRepoName(value: boolean): void {
    if (this.showRepoName === value) return;
    this.showRepoName = value;
    settingsStore.set("discordPresenceShowRepoName", value);
    this.render();
    this.emitStatus();
  }

  /** Update what the user is doing; rendered (rate-limited) onto Discord. */
  setActivity(intent: PresenceIntent): void {
    this.intent = intent;
    this.render();
  }

  @preDestroy()
  cleanup(): void {
    this.disconnect();
  }

  private connect(): void {
    if (!this.clientId) {
      log.warn(
        "No Discord Application ID is set; Discord Rich Presence will stay dormant",
      );
      return;
    }
    if (this.client) return;

    const client = new DiscordIpcClient(this.clientId);
    this.client = client;
    client.on("ready", () => {
      this.connected = true;
      this.waiting = false;
      log.info("Connected to Discord");
      this.render(true);
      this.emitStatus();
    });
    client.on("disconnect", () => {
      const wasConnected = this.connected;
      this.connected = false;
      if (wasConnected) {
        log.info("Lost Discord connection; retrying in the background");
        this.emitStatus();
      } else if (!this.waiting) {
        this.waiting = true;
        log.debug(
          "Discord not running; retrying in the background until it appears",
        );
        this.emitStatus();
      }
      this.scheduleReconnect();
    });
    client.connect();
  }

  private disconnect(): void {
    this.clearTimers();
    if (this.client) {
      this.client.destroy();
      this.client = null;
    }
    this.connected = false;
    this.waiting = false;
  }

  private scheduleReconnect(): void {
    if (!this.enabled || this.reconnectTimer) return;
    if (this.client) {
      this.client.destroy();
      this.client = null;
    }
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.enabled && !this.connected) this.connect();
    }, RECONNECT_INTERVAL_MS);
  }

  /**
   * Push the current intent to Discord, coalescing bursts to one update per
   * {@link MIN_UPDATE_INTERVAL_MS} with a trailing flush so the latest state
   * always lands without tripping Discord's rate limiter.
   */
  private render(immediate = false): void {
    if (!this.client || !this.connected) return;

    const elapsed = Date.now() - this.lastUpdateAt;
    if (!immediate && elapsed < MIN_UPDATE_INTERVAL_MS) {
      if (!this.throttleTimer) {
        this.throttleTimer = setTimeout(() => {
          this.throttleTimer = null;
          this.render(true);
        }, MIN_UPDATE_INTERVAL_MS - elapsed);
      }
      return;
    }

    if (this.throttleTimer) {
      clearTimeout(this.throttleTimer);
      this.throttleTimer = null;
    }
    this.lastUpdateAt = Date.now();
    this.client.setActivity(
      buildActivity(this.intent, {
        showTaskTitle: this.showTaskTitle,
        showRepoName: this.showRepoName,
        startedAt: this.startedAt,
      }),
    );
  }

  private clearTimers(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.throttleTimer) {
      clearTimeout(this.throttleTimer);
      this.throttleTimer = null;
    }
  }

  private emitStatus(): void {
    this.emit(DiscordPresenceServiceEvent.StatusChanged, this.getState());
  }
}
