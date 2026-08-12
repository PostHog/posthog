import { type ChildProcess, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { createServer } from "node:net";
import path from "node:path";
import { TypedEventEmitter } from "@posthog/shared";
import { POSTHOG_CODE_INTERNAL_CHILD_ENV } from "@posthog/shared/constants";
import type { WorkspaceConnection } from "@posthog/workspace-client/client";
import { injectable } from "inversify";
import { logger } from "../../utils/logger.js";

const HEALTH_POLL_INTERVAL_MS = 100;
const HEALTH_POLL_TIMEOUT_MS = 5_000;
const SHUTDOWN_GRACE_MS = 3_000;

const MAX_RESTART_ATTEMPTS = 5;
const RESTART_BASE_DELAY_MS = 500;
const RESTART_MAX_DELAY_MS = 30_000;

const log = logger.scope("workspace-server");

export const WorkspaceServerStatus = {
  Idle: "idle",
  Starting: "starting",
  Ready: "ready",
  Retrying: "retrying",
  Failed: "failed",
} as const;

export type WorkspaceServerStatus =
  (typeof WorkspaceServerStatus)[keyof typeof WorkspaceServerStatus];

export const WorkspaceServerEvent = {
  ConnectionLost: "connectionLost",
  StatusChanged: "statusChanged",
} as const;

export interface WorkspaceServerEvents {
  [WorkspaceServerEvent.ConnectionLost]: {
    code: number | null;
    signal: NodeJS.Signals | null;
  };
  [WorkspaceServerEvent.StatusChanged]: {
    status: WorkspaceServerStatus;
    attempt: number;
    error?: string;
  };
}

@injectable()
export class WorkspaceServerService extends TypedEventEmitter<WorkspaceServerEvents> {
  private readonly scriptPath = path.join(__dirname, "workspace-server.js");
  private child: ChildProcess | null = null;
  private connection: WorkspaceConnection | null = null;
  private pendingStart: Promise<WorkspaceConnection> | null = null;
  private status: WorkspaceServerStatus = WorkspaceServerStatus.Idle;
  private restartAttempts = 0;
  private restartTimer: NodeJS.Timeout | null = null;
  private stopping = false;

  getConnection(): WorkspaceConnection | null {
    return this.connection;
  }

  getStatus(): WorkspaceServerStatus {
    return this.status;
  }

  getStatusSnapshot(): { status: WorkspaceServerStatus; attempt: number } {
    return { status: this.status, attempt: this.restartAttempts };
  }

  start(): Promise<WorkspaceConnection> {
    if (this.connection) return Promise.resolve(this.connection);
    if (this.pendingStart) return this.pendingStart;

    this.stopping = false;
    this.clearRestartTimer();
    this.pendingStart = this.runStart();
    return this.pendingStart;
  }

  stop(): void {
    this.stopping = true;
    this.clearRestartTimer();
    this.restartAttempts = 0;
    this.setStatus(WorkspaceServerStatus.Idle);

    const c = this.child;
    this.child = null;
    this.connection = null;
    if (c) this.killChild(c);
  }

  /**
   * User-initiated restart, e.g. the renderer "Retry" action from the failed
   * state. Resets the attempt budget so the supervisor gets a fresh set of
   * retries, unlike the automatic restart path which keeps counting toward the
   * cap.
   */
  restart(): Promise<WorkspaceConnection> {
    this.stopping = false;
    this.clearRestartTimer();
    this.restartAttempts = 0;
    return this.start();
  }

  private async runStart(): Promise<WorkspaceConnection> {
    if (this.restartAttempts === 0) {
      this.setStatus(WorkspaceServerStatus.Starting);
    }
    try {
      const connection = await this.spawnChild();
      this.restartAttempts = 0;
      this.pendingStart = null;
      this.setStatus(WorkspaceServerStatus.Ready);
      return connection;
    } catch (error) {
      this.pendingStart = null;
      this.scheduleRestart(error);
      throw error;
    }
  }

  /**
   * Supervises restarts after an unexpected child exit or a failed start.
   * Backs off exponentially and gives up after MAX_RESTART_ATTEMPTS, leaving
   * the service in the "failed" state for the renderer to surface. The attempt
   * budget resets only once a child becomes healthy again.
   */
  private scheduleRestart(error?: unknown): void {
    if (this.stopping) return;
    if (this.pendingStart || this.restartTimer) return;

    if (this.restartAttempts >= MAX_RESTART_ATTEMPTS) {
      this.setStatus(WorkspaceServerStatus.Failed, errorMessage(error));
      return;
    }

    this.restartAttempts++;
    const delay = Math.min(
      RESTART_BASE_DELAY_MS * 2 ** (this.restartAttempts - 1),
      RESTART_MAX_DELAY_MS,
    );
    this.setStatus(WorkspaceServerStatus.Retrying, errorMessage(error));
    log.info("scheduling workspace-server restart", {
      attempt: this.restartAttempts,
      delayMs: delay,
    });
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      // A failed restart re-enters scheduleRestart through runStart's catch.
      void this.start().catch(() => {});
    }, delay);
    this.restartTimer.unref();
  }

  private clearRestartTimer(): void {
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
  }

  private setStatus(status: WorkspaceServerStatus, error?: string): void {
    this.status = status;
    this.emit(WorkspaceServerEvent.StatusChanged, {
      status,
      attempt: this.restartAttempts,
      error,
    });
  }

  private killChild(c: ChildProcess): void {
    try {
      c.kill("SIGTERM");
    } catch {}
    setTimeout(() => {
      try {
        c.kill("SIGKILL");
      } catch {}
    }, SHUTDOWN_GRACE_MS).unref();
  }

  private async spawnChild(): Promise<WorkspaceConnection> {
    const port = await findFreePort();
    const secret = randomBytes(32).toString("hex");
    const url = `http://127.0.0.1:${port}`;

    const c = spawn(process.execPath, [this.scriptPath], {
      detached: false,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        ELECTRON_RUN_AS_NODE: "1",
        [POSTHOG_CODE_INTERNAL_CHILD_ENV]: "1",
        WORKSPACE_SERVER_SECRET: secret,
        WORKSPACE_SERVER_PORT: String(port),
        WORKSPACE_SERVER_PARENT_PID: String(process.pid),
      },
      windowsHide: true,
    });

    c.stdout?.on("data", (chunk) => process.stdout.write(chunk));
    c.stderr?.on("data", (chunk) => process.stderr.write(chunk));
    c.once("exit", (code, signal) => {
      if (this.child !== c) return;
      const wasConnected = this.connection !== null;
      this.child = null;
      this.connection = null;
      log.info("child exited", { code, signal });
      if (wasConnected && !this.stopping) {
        this.emit(WorkspaceServerEvent.ConnectionLost, { code, signal });
        this.scheduleRestart();
      }
    });

    this.child = c;

    if (!(await pollHealth(url))) {
      this.child = null;
      this.killChild(c);
      throw new Error(
        `workspace-server failed to become healthy within ${HEALTH_POLL_TIMEOUT_MS}ms`,
      );
    }

    this.connection = { url, secret };
    return this.connection;
  }
}

function errorMessage(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}

async function findFreePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.unref();
    s.on("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const a = s.address();
      if (!a || typeof a === "string") {
        s.close();
        reject(new Error("failed to allocate port"));
        return;
      }
      const port = a.port;
      s.close(() => resolve(port));
    });
  });
}

async function pollHealth(url: string): Promise<boolean> {
  const deadline = Date.now() + HEALTH_POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(`${url}/health`)).ok) return true;
    } catch {}
    await new Promise((r) => setTimeout(r, HEALTH_POLL_INTERVAL_MS));
  }
  return false;
}
