import { isSupportedReasoningEffort } from "@posthog/agent/adapters/reasoning-effort";
import {
  REPORT_MODEL_RESOLVER,
  type ReportModelResolver,
} from "@posthog/core/inbox/identifiers";
import {
  isUsageLimitResult,
  TASK_SERVICE,
  type TaskCreationInput,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import {
  type Adapter,
  ANALYTICS_EVENTS,
  defaultEligibleModel,
  getCloudUrlFromRegion,
} from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { showOfflineToast } from "@posthog/ui/features/connectivity/connectivityToast";
import { resolveDefaultModel } from "@posthog/ui/features/inbox/hooks/resolveDefaultModel";
import { useUserRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useCreateTask } from "@posthog/ui/features/tasks/useTaskCrudMutations";
import { useConnectivity } from "@posthog/ui/hooks/useConnectivity";
import { toast } from "@posthog/ui/primitives/toast";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

/** Variant-specific copy used in the toasts/errors emitted by the runner. */
export interface InboxCloudTaskCopy {
  /** Toast shown while the task is being created. */
  loadingTitle: string;
  /** Toast title used for any failure (repo / integration / sign-in / mutation). */
  errorTitle: string;
  /** Error description when no repository is selected. */
  missingRepository: string;
  /** Error description when no GitHub integration is connected for the repo. */
  missingIntegration: string;
  /** Error description when the user is signed out. */
  signedOut: string;
  /** Error description when no model can be resolved. */
  missingModel: string;
  /**
   * Title for the success toast shown when `redirectOnSuccess` is false and the
   * runner stays in place instead of navigating to the task. Defaults to
   * "Task started".
   */
  successTitle?: string;
}

/** Context the variant uses to assemble the TaskCreationInput. */
export interface InboxCloudTaskInputContext {
  reportId?: string;
  reportTitle?: string | null;
  /**
   * Resolved repository, or null when the runner ran repo-less (only possible
   * when the caller sets `allowMissingRepository`). Variants that require a repo
   * never observe null here, since the runner bails before `buildInput`.
   */
  cloudRepository: string | null;
  /** Null alongside a null `cloudRepository` (repo-less run). */
  githubUserIntegrationId: string | null;
  adapter: Adapter;
  model: string;
  reasoningLevel?: string;
}

export interface UseInboxCloudTaskRunnerOptions {
  /** Backing signal report, when the task is report-scoped (Create PR, Discuss). */
  reportId?: string;
  reportTitle?: string | null;
  cloudRepository: string | null;
  /**
   * When true, a missing repository is not an error: the task is created
   * repo-less (no clone, no GitHub identity). The backend provisions a bare
   * sandbox in that case. Use for flows that only need the cloud sandbox plus
   * PostHog MCP — e.g. scout chats — never for flows that author a PR. Defaults
   * to false, preserving the repo + integration gate for Create-PR / Discuss.
   */
  allowMissingRepository?: boolean;
  copy: InboxCloudTaskCopy;
  /** Logger scope used for failure traces. */
  loggerScope: string;
  /** Build the TaskCreationInput from the resolved context (prompt, branch, etc.). */
  buildInput: (ctx: InboxCloudTaskInputContext) => TaskCreationInput;
  /** Telemetry extras merged into the TASK_CREATED event when the run succeeds. */
  analyticsExtras?: Record<string, unknown>;
  /** Called with the created task record, before any navigation happens. */
  onTaskCreated?: (task: Task) => void;
  /**
   * When false, the runner does not navigate to the created task. The task is
   * still added to the sidebar via `invalidateTasks`, and a success toast with a
   * "View task" action lets the user open it on demand. Defaults to true.
   */
  redirectOnSuccess?: boolean;
}

export interface UseInboxCloudTaskRunnerReturn {
  /** Kick off the cloud-task flow. Resolves after the task is created (or failed). */
  run: () => Promise<void>;
  /** True while a task is being created. */
  isRunning: boolean;
}

/**
 * Shared driver for one-click "create an auto-mode cloud task" flows
 * (Create PR, Discuss, scout fleet overview). Variants supply copy, telemetry,
 * and a `buildInput` callback that assembles the per-variant prompt / branch /
 * metadata; report context is optional for flows not scoped to a report.
 */
export function useInboxCloudTaskRunner({
  reportId,
  reportTitle,
  cloudRepository,
  allowMissingRepository = false,
  copy,
  loggerScope,
  buildInput,
  analyticsExtras,
  onTaskCreated,
  redirectOnSuccess = true,
}: UseInboxCloudTaskRunnerOptions): UseInboxCloudTaskRunnerReturn {
  const [isRunning, setIsRunning] = useState(false);
  const { getUserIntegrationIdForRepo } = useUserRepositoryIntegration();
  const { invalidateTasks } = useCreateTask();
  const taskService = useService<TaskService>(TASK_SERVICE);
  const modelResolver = useService<ReportModelResolver>(REPORT_MODEL_RESOLVER);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const queryClient = useQueryClient();
  const { isOnline } = useConnectivity();

  const run = useCallback(async () => {
    if (isRunning) return;
    const log = logger.scope(loggerScope);

    if (!isOnline) {
      showOfflineToast();
      return;
    }

    if (!cloudRepository && !allowMissingRepository) {
      toast.error(copy.errorTitle, { description: copy.missingRepository });
      return;
    }

    // A repo-less run has no GitHub identity; only resolve/require the user
    // integration when a repository is actually in play.
    const githubUserIntegrationId = cloudRepository
      ? getUserIntegrationIdForRepo(cloudRepository)
      : null;
    if (cloudRepository && !githubUserIntegrationId) {
      toast.error(copy.errorTitle, { description: copy.missingIntegration });
      return;
    }

    if (!cloudRegion) {
      toast.error(copy.errorTitle, { description: copy.signedOut });
      return;
    }

    setIsRunning(true);
    const toastId = toast.loading(copy.loadingTitle, reportTitle ?? undefined);

    const settings = useSettingsStore.getState();
    const adapter = settings.lastUsedAdapter ?? "claude";
    const apiHost = getCloudUrlFromRegion(cloudRegion);

    // Pass the persisted model as a *preference*, not a hard selection: the
    // resolver keeps it only if the gateway still offers it, otherwise it falls
    // back to the server default. A stale id (e.g. one later de-listed for the
    // org) would otherwise be sent here and fail the run with a gateway 403.
    const preferredModel = defaultEligibleModel(settings.lastUsedModel);
    const resolvedModel = await resolveDefaultModel(
      queryClient,
      apiHost,
      adapter,
      modelResolver,
      preferredModel,
    );
    // The resolver returns undefined on a transient failure; fall back to the
    // persisted id so a gateway outage degrades gracefully rather than blocking.
    const model = resolvedModel ?? preferredModel;

    if (!model) {
      toast.dismiss(toastId);
      toast.error(copy.errorTitle, { description: copy.missingModel });
      setIsRunning(false);
      return;
    }

    // The persisted effort belongs to `lastUsedModel`; if the resolver swapped in
    // a fallback default, that tier may be unsupported for the new model and the
    // cloud runtime rejects the pair (see agent `bin.ts`). Carry the effort only
    // when the model is unchanged AND the tier is actually supported for it —
    // an effort-less model (e.g. a Cloudflare `@cf/*` model) carrying a stale
    // tier would otherwise hard-fail the run at startup. Otherwise let the
    // runtime pick its default.
    const reasoningLevel =
      model === settings.lastUsedModel &&
      settings.lastUsedReasoningEffort &&
      isSupportedReasoningEffort(
        adapter,
        model,
        settings.lastUsedReasoningEffort,
      )
        ? settings.lastUsedReasoningEffort
        : undefined;

    const input = buildInput({
      reportId,
      reportTitle,
      cloudRepository,
      githubUserIntegrationId: githubUserIntegrationId
        ? String(githubUserIntegrationId)
        : null,
      adapter,
      model,
      reasoningLevel,
    });

    try {
      let createdTask: Parameters<typeof openTask>[0] | null = null;
      const result = await taskService.createTask(input, (output) => {
        createdTask = output.task;
        invalidateTasks(output.task);
        onTaskCreated?.(output.task);
        if (redirectOnSuccess) {
          void openTask(output.task);
        }
      });

      if (result.success) {
        toast.dismiss(toastId);
        if (!redirectOnSuccess) {
          const task = createdTask;
          toast.success(copy.successTitle ?? "Task started", {
            description: reportTitle ?? undefined,
            action: task
              ? {
                  label: "View task",
                  onClick: () => {
                    void openTask(task);
                  },
                }
              : undefined,
          });
        }
        track(ANALYTICS_EVENTS.TASK_CREATED, {
          auto_run: true,
          created_from: "command-menu",
          ...(cloudRepository ? { repository_provider: "github" } : {}),
          workspace_mode: "cloud",
          ...(reportId
            ? {
                cloud_run_source: "signal_report",
                cloud_pr_authorship_mode: "user",
                signal_report_id: reportId,
              }
            : { cloud_run_source: "manual" }),
          adapter,
          ...analyticsExtras,
        });
      } else {
        toast.dismiss(toastId);
        // Usage-limit blocks already show the upgrade modal; don't double-toast.
        if (!isUsageLimitResult(result)) {
          toastError(copy.errorTitle, result.error);
          log.error("Cloud-task creation failed", {
            failedStep: result.failedStep,
            error: result.error,
            reportId,
            reportTitle,
          });
        }
      }
    } catch (error) {
      toast.dismiss(toastId);
      toastError(copy.errorTitle, error);
      log.error("Unexpected error during cloud-task creation", {
        error,
        reportId,
      });
    } finally {
      setIsRunning(false);
    }
  }, [
    isRunning,
    isOnline,
    loggerScope,
    cloudRepository,
    allowMissingRepository,
    cloudRegion,
    reportId,
    reportTitle,
    getUserIntegrationIdForRepo,
    invalidateTasks,
    queryClient,
    buildInput,
    copy,
    analyticsExtras,
    onTaskCreated,
    modelResolver,
    taskService,
    redirectOnSuccess,
  ]);

  return { run, isRunning };
}
