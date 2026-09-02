import type {
  GitInteractionEffects,
  IGitWriteClient,
} from "@posthog/core/git-interaction/gitInteractionService";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import {
  ANALYTICS_EVENTS,
  buildPrOutput,
  mergePrUrls,
  promotePrUrl,
  readPrUrls,
} from "@posthog/shared";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { celebrate } from "@posthog/ui/primitives/confetti";
import { track } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

const log = logger.scope("git-interaction");

function host(): HostTrpcClient {
  return resolveService<HostTrpcClient>(HOST_TRPC_CLIENT);
}

export const gitWriteClient: IGitWriteClient = {
  commit: (input) => host().git.commit.mutate(input),
  push: (directoryPath, signal) =>
    host().git.push.mutate({ directoryPath }, { signal }),
  sync: (directoryPath, signal) =>
    host().git.sync.mutate({ directoryPath }, { signal }),
  publish: (directoryPath, signal) =>
    host().git.publish.mutate({ directoryPath }, { signal }),
  createBranch: async (directoryPath, branchName) => {
    await host().git.createBranch.mutate({ directoryPath, branchName });
  },
  createPr: (input) => host().git.createPr.mutate(input),
  openPr: (directoryPath) => host().git.openPr.mutate({ directoryPath }),
  generateCommitMessage: (input) =>
    host().git.generateCommitMessage.mutate(input),
  generatePrTitleAndBody: (input) =>
    host().git.generatePrTitleAndBody.mutate(input),
  linkBranch: async (taskId, branchName) => {
    await host().workspace.linkBranch.mutate({ taskId, branchName });
  },
  onCreatePrProgress: (flowId, onStep) => {
    const subscription = host().git.onCreatePrProgress.subscribe(undefined, {
      onData: (data) => {
        if (data.flowId !== flowId) return;
        onStep(data.step);
      },
    });
    return () => subscription.unsubscribe();
  },
};

function getConversationContext(taskId: string): string | undefined {
  const state = useSessionStore.getState();
  const taskRunId = state.taskIdIndex[taskId];
  if (!taskRunId) return undefined;
  return state.sessions[taskRunId]?.conversationSummary;
}

function attachPrUrlToTask(
  taskId: string,
  prUrl: string,
  prTitle?: string,
): void {
  const state = useSessionStore.getState();
  const taskRunId = state.taskIdIndex[taskId];
  if (!taskRunId) return;
  const sessionUrls = readPrUrls(state.sessions[taskRunId]?.cloudOutput);
  const conversationContext = getConversationContext(taskId);
  void getAuthenticatedClient().then(async (client) => {
    if (!client) return;
    try {
      const [freshOutput, summary] = await Promise.all([
        client
          .getTaskRun(taskId, taskRunId)
          .then((run) => run.output)
          .catch(() => null),
        conversationContext || prTitle
          ? host()
              .git.generatePrShortSummary.mutate({
                conversationContext,
                prTitle,
              })
              .then((r) => r.summary || null)
              .catch(() => null)
          : Promise.resolve(null),
      ]);
      const urls = mergePrUrls(readPrUrls(freshOutput), sessionUrls, [prUrl]);
      await client.updateTaskRun(taskId, taskRunId, {
        output: buildPrOutput(
          freshOutput,
          urls,
          summary ? { [prUrl]: summary } : undefined,
        ),
      });
    } catch (err) {
      log.warn("Failed to attach PR URL to task", { taskId, prUrl, err });
    }
  });
}

const summaryBackfillAttempts = new Set<string>();

export async function backfillPrSummaries(
  taskId: string,
  urls: string[],
  existingSummaries: Record<string, string>,
): Promise<boolean> {
  const taskRunId = useSessionStore.getState().taskIdIndex[taskId];
  if (!taskRunId) return false;
  const missing = urls.filter((url) => {
    const key = `${taskRunId}|${url}`;
    if (existingSummaries[url] || summaryBackfillAttempts.has(key)) {
      return false;
    }
    summaryBackfillAttempts.add(key);
    return true;
  });
  if (missing.length === 0) return false;
  const conversationContext = getConversationContext(taskId);
  const client = await getAuthenticatedClient();
  if (!client) return false;
  try {
    const generated = await Promise.all(
      missing.map(async (url) => {
        const title = await host()
          .git.getPrDetailsByUrl.query({ prUrl: url })
          .then((details) => details.title ?? undefined)
          .catch(() => undefined);
        if (!conversationContext && !title) return null;
        const summary = await host()
          .git.generatePrShortSummary.mutate({
            conversationContext,
            prTitle: title,
          })
          .then((r) => r.summary || null)
          .catch(() => null);
        return summary ? ([url, summary] as const) : null;
      }),
    );
    const summaries = Object.fromEntries(
      generated.filter((entry) => entry !== null),
    );
    if (Object.keys(summaries).length === 0) return false;
    const freshOutput = await client
      .getTaskRun(taskId, taskRunId)
      .then((run) => run.output)
      .catch(() => null);
    const cloudUrls = readPrUrls(freshOutput);
    if (cloudUrls.length === 0) return false;
    await client.updateTaskRun(taskId, taskRunId, {
      output: buildPrOutput(freshOutput, cloudUrls, summaries),
    });
    return true;
  } catch (err) {
    log.warn("Failed to backfill PR summaries", { taskId, err });
    return false;
  }
}

export async function promoteTaskPrUrl(
  taskId: string,
  prUrl: string,
): Promise<void> {
  host()
    .workspace.setPrimaryPrUrl.mutate({ taskId, prUrl })
    .catch((err) =>
      log.warn("Failed to promote PR locally", { taskId, prUrl, err }),
    );

  const taskRunId = useSessionStore.getState().taskIdIndex[taskId];
  if (!taskRunId) return;
  const client = await getAuthenticatedClient();
  if (!client) return;
  const freshOutput = await client
    .getTaskRun(taskId, taskRunId)
    .then((run) => run.output)
    .catch(() => null);
  const urls = promotePrUrl(readPrUrls(freshOutput), prUrl);
  await client.updateTaskRun(taskId, taskRunId, {
    output: buildPrOutput(freshOutput, urls),
  });
}

export const gitInteractionEffects: GitInteractionEffects = {
  trackGitAction: (taskId, actionType, success, stagingContext) => {
    track(ANALYTICS_EVENTS.GIT_ACTION_EXECUTED, {
      action_type: actionType,
      success,
      task_id: taskId,
      ...stagingContext,
    });
  },
  trackPrCreated: (taskId, success) => {
    track(ANALYTICS_EVENTS.PR_CREATED, { task_id: taskId, success });
  },
  hasShippedFirstPr: () => useOnboardingStore.getState().hasShippedFirstPr,
  markFirstPrShipped: () => useOnboardingStore.getState().markFirstPrShipped(),
  celebrate: () => celebrate(),
  openExternalUrl: (url) => openExternalUrl(url),
  attachPrUrlToTask,
  getConversationContext,
  logError: (message, error) => log.error(message, error),
  logWarn: (message, context) => log.warn(message, context),
};
