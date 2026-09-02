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

export interface TaskLinkCommentAnchor {
  threadId: string;
  scope?: string;
  itemId?: string;
}

export interface TaskLinkPayload {
  taskId: string;
  taskRunId?: string;
  comment?: TaskLinkCommentAnchor;
}

export interface TaskLinkEvents {
  [TaskLinkEvent.OpenTask]: TaskLinkPayload;
}

export type PendingDeepLink = TaskLinkPayload;

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

    this.deepLinkService.registerHandler("task", (path, searchParams) =>
      this.handleTaskLink(path, searchParams),
    );
  }

  private handleTaskLink(path: string, searchParams: URLSearchParams): boolean {
    const parts = path.split("/");
    const taskId = parts[0];
    const taskRunId = parts[1] === "run" ? parts[2] : undefined;

    if (!taskId) {
      this.log.warn("Task link missing task ID");
      return false;
    }

    const threadId = searchParams.get("comment");
    const comment: TaskLinkCommentAnchor | undefined = threadId
      ? {
          threadId,
          scope: searchParams.get("scope") ?? undefined,
          itemId: searchParams.get("item") ?? undefined,
        }
      : undefined;
    return this.openTask({ taskId, taskRunId, comment });
  }

  /** Routes the main window to a task, queueing until the renderer is ready. */
  public openTask(payload: TaskLinkPayload): boolean {
    const { taskId, taskRunId, comment } = payload;
    const hasListeners = this.listenerCount(TaskLinkEvent.OpenTask) > 0;

    if (hasListeners) {
      this.log.info(
        `Emitting task link event: taskId=${taskId}, taskRunId=${taskRunId ?? "none"}, comment=${comment?.threadId ?? "none"}`,
      );
      this.emit(TaskLinkEvent.OpenTask, payload);
    } else {
      this.log.info(
        `Queueing task link (renderer not ready): taskId=${taskId}, taskRunId=${taskRunId ?? "none"}, comment=${comment?.threadId ?? "none"}`,
      );
      this.pendingDeepLink = payload;
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
