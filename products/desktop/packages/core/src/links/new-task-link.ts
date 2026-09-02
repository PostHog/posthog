import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  DEEP_LINK_SERVICE,
  type IDeepLinkRegistry,
} from "@posthog/platform/deep-link";
import {
  type IMainWindow,
  MAIN_WINDOW_SERVICE,
} from "@posthog/platform/main-window";
import {
  decodePlanBase64,
  type NewTaskLinkPayload,
  type NewTaskSharedParams,
  parseGitHubIssueUrl,
  TypedEventEmitter,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { LinkLogger } from "./identifiers";

export const NewTaskLinkEvent = {
  Action: "action",
} as const;

export type { NewTaskLinkPayload };

export interface NewTaskLinkEvents {
  [NewTaskLinkEvent.Action]: NewTaskLinkPayload;
}

@injectable()
export class NewTaskLinkService extends TypedEventEmitter<NewTaskLinkEvents> {
  private pendingLink: NewTaskLinkPayload | null = null;
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
    this.log = rootLogger.scope("new-task-link-service");

    this.deepLinkService.registerHandler("new", (_path, params) =>
      this.handleNew(params),
    );
    this.deepLinkService.registerHandler("plan", (_path, params) =>
      this.handlePlan(params),
    );
    this.deepLinkService.registerHandler("issue", (_path, params) =>
      this.handleIssue(params),
    );
  }

  private extractSharedParams(params: URLSearchParams): NewTaskSharedParams {
    return {
      repo: params.get("repo") ?? undefined,
      mode: params.get("mode") ?? undefined,
      model: params.get("model") ?? undefined,
    };
  }

  private handleNew(params: URLSearchParams): boolean {
    const shared = this.extractSharedParams(params);
    const prompt = params.get("prompt") ?? undefined;

    if (!prompt && !shared.repo) {
      this.log.warn("New task link requires at least prompt or repo");
      return false;
    }

    const payload: NewTaskLinkPayload = {
      action: "new",
      prompt,
      ...shared,
    };

    this.log.info("Handling new task link", {
      hasPrompt: !!prompt,
      repo: shared.repo,
    });
    return this.emitOrQueue(payload);
  }

  private handlePlan(params: URLSearchParams): boolean {
    const planEncoded = params.get("plan");

    if (!planEncoded) {
      this.log.warn("Plan link missing plan parameter");
      return false;
    }

    const plan = decodePlanBase64(planEncoded);
    if (plan === null) {
      this.log.error("Plan link has invalid base64 encoding");
      return false;
    }

    const shared = this.extractSharedParams(params);
    const payload: NewTaskLinkPayload = {
      action: "plan",
      plan,
      ...shared,
    };

    this.log.info("Handling plan link", {
      planLength: plan.length,
      repo: shared.repo,
    });
    return this.emitOrQueue(payload);
  }

  private handleIssue(params: URLSearchParams): boolean {
    const url = params.get("url");

    if (!url) {
      this.log.warn("Issue link missing url parameter");
      return false;
    }

    const parsed = parseGitHubIssueUrl(url);
    if (!parsed) {
      this.log.warn("Issue link has invalid GitHub issue URL", { url });
      return false;
    }

    const shared = this.extractSharedParams(params);
    const payload: NewTaskLinkPayload = {
      action: "issue",
      url,
      owner: parsed.owner,
      issueRepo: parsed.repo,
      issueNumber: parsed.number,
      ...shared,
    };

    this.log.info("Handling issue link", {
      owner: parsed.owner,
      repo: parsed.repo,
      number: parsed.number,
    });
    return this.emitOrQueue(payload);
  }

  private emitOrQueue(payload: NewTaskLinkPayload): boolean {
    const hasListeners = this.listenerCount(NewTaskLinkEvent.Action) > 0;

    if (hasListeners) {
      this.log.info(`Emitting new task link event: action=${payload.action}`);
      this.emit(NewTaskLinkEvent.Action, payload);
    } else {
      this.log.info(
        `Queueing new task link (renderer not ready): action=${payload.action}`,
      );
      this.pendingLink = payload;
    }

    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }
    this.mainWindow.focus();

    return true;
  }

  public consumePendingLink(): NewTaskLinkPayload | null {
    const pending = this.pendingLink;
    this.pendingLink = null;
    if (pending) {
      this.log.info(`Consumed pending new task link: action=${pending.action}`);
    }
    return pending;
  }
}
