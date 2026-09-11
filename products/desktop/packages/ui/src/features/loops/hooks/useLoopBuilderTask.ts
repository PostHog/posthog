import type { TaskCreationInput } from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import { LOOPS_HOG_FLOWS_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { getAuthIdentity, useAuthStore } from "@posthog/ui/features/auth/store";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import {
  resolveFeatureFlagAfterLoad,
  useFeatureFlagsLoaded,
} from "@posthog/ui/features/feature-flags/useFeatureFlagsLoaded";
import {
  type InboxCloudTaskInputContext,
  useInboxCloudTaskRunner,
} from "@posthog/ui/features/inbox/hooks/useInboxCloudTaskRunner";
import { useCallback, useMemo, useRef } from "react";
import {
  buildLoopBuilderSystemInstructions,
  type LoopBuilderBackend,
} from "../loopBuilderPrompt";
import { useLoopBuilderSessionStore } from "../loopBuilderSessionStore";

interface UseLoopBuilderTaskReturn {
  /** Start an auto-mode cloud session that builds a loop from `instructions` and navigate to it. */
  runTask: (instructions: string) => Promise<void>;
  /** True while the session is being created. */
  isRunning: boolean;
}

/**
 * The loops prompt box: start a cloud sandbox agent whose job is to build a Loop
 * with the user (ask clarifying questions, confirm, then create it through the
 * PostHog MCP: `loops-create`, or the `workflows-*` tools when loops are
 * workflow-backed). Mirrors `useScoutChatTask`: a repo-less, auto-mode cloud
 * task seeded with a canned instruction prompt. The user's typed text rides in
 * through a ref so the fixed `buildInput` closure reads the latest submission.
 */
export function useLoopBuilderTask(context?: {
  folderId: string;
  name: string;
}): UseLoopBuilderTaskReturn {
  const instructionsRef = useRef("");
  const contextRef = useRef(context);
  contextRef.current = context;
  // Resolved per submit, after flags load: a submit on a cold identity must
  // not seed the legacy briefing while the Loops screens read workflows.
  const featureFlags = useService<FeatureFlags>(FEATURE_FLAGS);
  const featureFlagsLoaded = useFeatureFlagsLoaded();
  const backendRef = useRef<LoopBuilderBackend>("loops");

  const buildInput = useCallback(
    (ctx: InboxCloudTaskInputContext): TaskCreationInput => {
      const userPrompt = instructionsRef.current.trim();
      const hasSeed = !!userPrompt;
      const systemInstructions = buildLoopBuilderSystemInstructions({
        hasSeed,
        context: contextRef.current,
        backend: backendRef.current,
      });
      // createTask rejects empty content and the saga drops customInstructions without message text
      const taskContent = hasSeed ? userPrompt : "Build a loop";
      return {
        content: taskContent,
        // Divergent on purpose: the description becomes the task's title, so
        // the "Loop builder:" prefix marks the sidebar row as a builder session.
        taskDescription: hasSeed
          ? `Loop builder: ${userPrompt}`
          : "Loop builder",
        customInstructions: systemInstructions,
        // Building a loop is pure PostHog-MCP work (listing, then creating the
        // loop or workflow); it never touches a working tree. Run repo-less so the
        // sandbox skips the clone and isn't tied to some arbitrary default repo.
        repository: undefined,
        githubUserIntegrationId: undefined,
        workspaceMode: "cloud",
        executionMode: "acceptEdits",
        adapter: ctx.adapter,
        model: ctx.model,
        reasoningLevel: ctx.reasoningLevel,
      };
    },
    [],
  );

  const copy = useMemo(
    () => ({
      loadingTitle: "Starting loop builder...",
      errorTitle: "Failed to start loop builder",
      missingRepository: "Connect a GitHub repository before building a loop",
      missingIntegration: "Connect a GitHub integration to build a loop",
      signedOut: "Sign in to build a loop",
      missingModel:
        "Couldn't resolve a default model. Open a task once and pick a model, then try again.",
    }),
    [],
  );

  const handleTaskCreated = useCallback((task: Task) => {
    const identity = getAuthIdentity(useAuthStore.getState().authState);
    if (!identity) return;
    useLoopBuilderSessionStore.getState().addSession({
      taskId: task.id,
      prompt: instructionsRef.current.trim() || "Build a loop",
      startedAt: Date.now(),
      identity,
    });
  }, []);

  const { run, isRunning } = useInboxCloudTaskRunner({
    // The loop builder never needs a repo: run repo-less so the sandbox does no
    // clone and no GitHub identity is attached.
    cloudRepository: null,
    allowMissingRepository: true,
    loggerScope: "loop-builder",
    copy,
    buildInput,
    onTaskCreated: handleTaskCreated,
  });

  const runTask = useCallback(
    async (instructions: string) => {
      instructionsRef.current = instructions;
      const workflowBacked = await resolveFeatureFlagAfterLoad(
        featureFlags,
        LOOPS_HOG_FLOWS_FLAG,
        featureFlagsLoaded,
      );
      backendRef.current = workflowBacked ? "workflow" : "loops";
      await run();
    },
    [run, featureFlags, featureFlagsLoaded],
  );

  return { runTask, isRunning };
}
