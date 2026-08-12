import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  DEEP_LINK_SERVICE,
  type IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import { TypedEventEmitter } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { LinkLogger } from "./identifiers";

export const TaskLinkEvent = {
  OpenTask: "openTask",
} as const;

export interface TaskLinkEvents {
  [TaskLinkEvent.OpenTask]: { taskId: string; taskRunId?: string };
}

export interface PendingDeepLink {
  taskId: string;
  taskRunId?: string;
}

@injectable()
export class TaskLinkService extends TypedEventEmitter<TaskLinkEvents> {
  private pendingDeepLink: PendingDeepLink | null = null;
  private readonly log: LinkLogger;

  constructor(
    @inject(DEEP_LINK_SERVICE)
    private readonly deepLinkService: IDeepLinkRegistry,
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: IMainWindow,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    super();
    this.log = rootLogger.scope("task-link-service");

    this.deepLinkService.registerHandler("task", (path) =>
      this.handleTaskLink(path),
    );
  }

  private handleTaskLink(path: string): boolean {
    const parts = path.split("/");
    const taskId = parts[0];
    const taskRunId = parts[1] === "run" ? parts[2] : undefined;

    if (!taskId) {
      this.log.warn("Task link missing task ID");
      return false;
    }

    const hasListeners = this.listenerCount(TaskLinkEvent.OpenTask) > 0;

    if (hasListeners) {
      this.log.info(
        `Emitting task link event: taskId=${taskId}, taskRunId=${taskRunId ?? "none"}`,
      );
      this.emit(TaskLinkEvent.OpenTask, { taskId, taskRunId });
    } else {
      this.log.info(
        `Queueing task link (renderer not ready): taskId=${taskId}, taskRunId=${taskRunId ?? "none"}`,
      );
      this.pendingDeepLink = { taskId, taskRunId };
    }

    this.log.info("Deep link focusing window", { taskId, taskRunId });
    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingDeepLink(): PendingDeepLink | null {
    const pending = this.pendingDeepLink;
    this.pendingDeepLink = null;
    if (pending) {
      this.log.info(
        `Consumed pending task link: taskId=${pending.taskId}, taskRunId=${pending.taskRunId ?? "none"}`,
      );
    }
    return pending;
  }
}
