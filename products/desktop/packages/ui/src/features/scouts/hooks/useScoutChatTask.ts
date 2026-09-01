import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import type { ScoutChatType, ScoutSurface } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { useUserRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import {
  resolveDefaultCloudRepository,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import { useCallback, useMemo } from "react";

interface UseScoutChatTaskOptions {
  /** The templated question the task is created with. */
  prompt: string;
  /** Short noun used in toast copy, e.g. "fleet overview". */
  taskLabel: string;
  /** Logger scope used for failure traces. */
  loggerScope: string;
  /** Which templated question this is, for analytics. */
  chatType: ScoutChatType;
  /** Where the CTA lives, for analytics. */
  surface: ScoutSurface;
  /** The scout a check-in is scoped to; omit for fleet-level questions. */
  skillName?: string;
}

interface UseScoutChatTaskReturn {
  /** Create the auto-mode scout chat task and navigate to it on success. */
  runTask: () => Promise<void>;
  /** True while the task is being created. */
  isRunning: boolean;
}

/**
 * One-click scout chat task, mirroring the inbox discuss flow: create an
 * auto-mode cloud task from a templated question and jump straight to it. The
 * repository falls back to the last-used cloud repository, then the first
 * connected one.
 */
export function useScoutChatTask({
  prompt,
  taskLabel,
  loggerScope,
  chatType,
  surface,
  skillName,
}: UseScoutChatTaskOptions): UseScoutChatTaskReturn {
  const { repositories } = useUserRepositoryIntegration();
  const lastUsedCloudRepository = useSettingsStore(
    (state) => state.lastUsedCloudRepository,
  );

  const cloudRepository = useMemo(
    () => resolveDefaultCloudRepository(repositories, lastUsedCloudRepository),
    [lastUsedCloudRepository, repositories],
  );

  const buildInput = useCallback(
    (ctx: InboxCloudTaskInputContext): TaskCreationInput => ({
      content: prompt,
      taskDescription: prompt,
      // Scout chats only need the cloud sandbox + PostHog MCP, so they run
      // repo-less when no personal GitHub repo is resolvable. When one is
      // available it's passed through (harmless, enables PR authorship).
      repository: ctx.cloudRepository,
      githubUserIntegrationId: ctx.githubUserIntegrationId ?? undefined,
      workspaceMode: "cloud",
      executionMode: "auto",
      adapter: ctx.adapter,
      model: ctx.model,
      reasoningLevel: ctx.reasoningLevel,
    }),
    [prompt],
  );

  const copy = useMemo(
    () => ({
      loadingTitle: `Starting ${taskLabel}...`,
      errorTitle: `Failed to start ${taskLabel}`,
      missingRepository: `Connect a GitHub repository before starting a ${taskLabel}`,
      missingIntegration: `Connect a GitHub integration to start a ${taskLabel}`,
      signedOut: `Sign in to start a ${taskLabel}`,
      missingModel:
        "Couldn't resolve a default model. Open the task page once and pick a model, then try again.",
    }),
    [taskLabel],
  );

  const { run, isRunning } = useInboxCloudTaskRunner({
    cloudRepository,
    // Authoring or asking about scouts is pure PostHog-MCP work; a missing repo
    // must not block it. Without this, a user with only a team-level GitHub
    // integration (no personal install) hit a confusing "Connect a GitHub
    // repository" failure even though scouts never touch repo code.
    allowMissingRepository: true,
    loggerScope,
    copy,
    buildInput,
  });

  const runTask = useCallback(async () => {
    track(ANALYTICS_EVENTS.SCOUT_CHAT_STARTED, {
      chat_type: chatType,
      surface,
      ...(skillName ? { skill_name: skillName } : {}),
    });
    await run();
  }, [run, chatType, surface, skillName]);

  return { runTask, isRunning };
}
