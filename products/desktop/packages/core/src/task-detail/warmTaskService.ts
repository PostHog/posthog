import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { inject, injectable } from "inversify";

export const WARM_TASK_SERVICE = Symbol.for(
  "posthog.core.taskDetail.warmTaskService",
);

export type WarmTaskOptions = Parameters<PostHogAPIClient["warmTask"]>[0];
export type WarmTaskClient = Pick<
  PostHogAPIClient,
  "warmTask" | "cancelTaskRun"
>;
export interface WarmTaskLease {
  taskId: string;
  runId: string;
  permissionModeMutable?: boolean;
}

export function warmTaskKey(options: WarmTaskOptions): string {
  return JSON.stringify([
    options.repositories ?? (options.repository ? [options.repository] : []),
    options.github_integration ?? null,
    options.branch ?? null,
    options.runtime_adapter ?? null,
    options.model ?? null,
    options.initial_permission_mode ?? null,
    options.sandbox_environment_id ?? null,
    options.custom_image_id ?? null,
  ]);
}

function warmTaskMatches(
  previous: WarmTaskOptions,
  next: WarmTaskOptions,
  mutableMode: boolean,
): boolean {
  return (
    warmTaskKey(previous) ===
    warmTaskKey(
      mutableMode
        ? { ...next, initial_permission_mode: previous.initial_permission_mode }
        : next,
    )
  );
}

export interface WarmTaskSubmission {
  take(options: WarmTaskOptions): WarmTaskLease | null;
  finish(success: boolean, taskId?: string): void;
}

interface WarmSelection {
  options: WarmTaskOptions;
  client: WarmTaskClient;
  key: string;
}

interface WarmAttempt {
  selection: WarmSelection;
  releaseKey: () => void;
  lease: WarmTaskLease | null;
  invalidated: boolean;
}

export class WarmTaskDraft {
  private timer: ReturnType<typeof setTimeout> | undefined;
  private attempted = false;
  private submitting = false;
  private owners = 0;
  private selection: WarmSelection | null = null;
  private attempt: WarmAttempt | null = null;

  constructor(
    private readonly acquireKey: (key: string) => (() => void) | null,
    private readonly warn: (error: unknown) => void,
  ) {}

  attach(): () => void {
    this.owners++;
    return () => {
      this.owners--;
      queueMicrotask(() => {
        if (!this.owners && !this.submitting) this.update(null, null);
      });
    };
  }

  private clearTimer(): void {
    if (this.timer !== undefined) clearTimeout(this.timer);
    this.timer = undefined;
  }

  private release(attempt: WarmAttempt): void {
    attempt.invalidated = true;
    const lease = attempt.lease;
    attempt.lease = null;
    if (lease) {
      void attempt.selection.client
        .cancelTaskRun(lease.taskId, lease.runId, undefined, true)
        .catch(this.warn)
        .finally(attempt.releaseKey);
    }
  }

  update(options: WarmTaskOptions | null, client: WarmTaskClient | null): void {
    if (this.submitting) return;
    const key = options && client ? warmTaskKey(options) : null;
    if (key === this.selection?.key) {
      if (options && this.selection) this.selection.options = options;
      return;
    }
    if (
      options &&
      client &&
      key &&
      this.attempt &&
      warmTaskMatches(
        this.attempt.selection.options,
        options,
        !this.attempt.lease ||
          this.attempt.lease.permissionModeMutable === true,
      )
    ) {
      this.selection = { options, client, key };
      return;
    }
    this.clearTimer();
    if (this.attempt) this.release(this.attempt);
    this.attempt = null;
    this.selection = options && client && key ? { options, client, key } : null;
    if (this.attempted || !this.selection) return;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      const selection = this.selection;
      if (!selection) return;
      this.attempted = true;
      const releaseKey = this.acquireKey(selection.key);
      if (!releaseKey) return;
      const attempt: WarmAttempt = {
        selection,
        releaseKey,
        lease: null,
        invalidated: false,
      };
      this.attempt = attempt;
      void selection.client
        .warmTask(selection.options)
        .then((warm) => {
          if (!warm) {
            releaseKey();
            return;
          }
          attempt.lease = {
            taskId: warm.task_id,
            runId: warm.run_id,
            ...(warm.permission_mode_mutable
              ? { permissionModeMutable: true }
              : {}),
          };
          if (
            attempt.invalidated ||
            !this.selection ||
            !warmTaskMatches(
              attempt.selection.options,
              this.selection.options,
              warm.permission_mode_mutable === true,
            )
          )
            this.release(attempt);
        })
        .catch((error) => {
          releaseKey();
          this.warn(error);
        });
    }, 600);
  }

  beginSubmission(): WarmTaskSubmission | null {
    if (this.submitting) return null;
    this.submitting = true;
    this.clearTimer();
    const attempt = this.attempt;
    this.attempt = null;
    this.selection = null;
    if (attempt && !attempt.lease) this.release(attempt);
    let taken = false;
    let finished = false;
    return {
      take: (options) => {
        if (taken || finished || !attempt?.lease || attempt.invalidated)
          return null;
        const requested = {
          ...options,
          github_integration:
            options.github_integration ??
            attempt.selection.options.github_integration,
        };
        if (
          !warmTaskMatches(
            attempt.selection.options,
            requested,
            attempt.lease.permissionModeMutable === true,
          )
        )
          return null;
        taken = true;
        return attempt.lease;
      },
      finish: (success, taskId) => {
        if (finished) return;
        finished = true;
        if (attempt?.lease) {
          if (!success || !taken || taskId !== attempt.lease.taskId)
            this.release(attempt);
          else attempt.releaseKey();
        }
        this.submitting = false;
        if (success) this.attempted = false;
      },
    };
  }
}

@injectable()
export class WarmTaskService {
  private readonly drafts = new Map<string, WarmTaskDraft>();
  private readonly keys = new Set<string>();
  private readonly log: ReturnType<RootLogger["scope"]>;

  constructor(@inject(ROOT_LOGGER) logger: RootLogger) {
    this.log = logger.scope("warm-task");
  }

  draft(scope: string, sessionId: string): WarmTaskDraft {
    const id = JSON.stringify([scope, sessionId]);
    const existing = this.drafts.get(id);
    if (existing) return existing;
    const draft = new WarmTaskDraft(
      (key) => {
        const scopedKey = JSON.stringify([scope, key]);
        if (this.keys.has(scopedKey)) return null;
        this.keys.add(scopedKey);
        return () => this.keys.delete(scopedKey);
      },
      (error) =>
        this.log.warn("Could not provision or release warm task", { error }),
    );
    this.drafts.set(id, draft);
    return draft;
  }
}
