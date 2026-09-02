import { sanitizeBranchName } from "@posthog/core/git-interaction/branchName";
import type { DiffStats } from "@posthog/core/git-interaction/diffStats";
import { partitionByStaged } from "@posthog/core/git-interaction/diffStats";
import { computeGitInteractionState } from "@posthog/core/git-interaction/gitInteractionLogic";
import type { GitInteractionService } from "@posthog/core/git-interaction/gitInteractionService";
import { GIT_INTERACTION_SERVICE } from "@posthog/core/git-interaction/identifiers";
import {
  deriveCreatePrPlan,
  deriveStagingPlan,
} from "@posthog/core/git-interaction/stagingPlan";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import type { ChangedFile } from "@posthog/shared/domain-types";
import { useConnectivity } from "@posthog/ui/hooks/useConnectivity";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef } from "react";
import { WORKSPACE_QUERY_KEY } from "../workspace/identifiers";
import { invalidateGitBranchQueries } from "./gitCacheKeys";
import {
  GIT_CACHE_KEY_PROVIDER,
  type GitCacheKeyProvider,
} from "./gitCacheProvider";
import {
  type GitInteractionStore,
  useGitInteractionStore,
} from "./state/gitInteractionStore";
import type {
  CommitNextStep,
  GitMenuAction,
  GitMenuActionId,
  PushMode,
} from "./types";
import { useGitQueries } from "./useGitQueries";
import { getBranchNameInputState } from "./utils/branchCreation";
import { getSuggestedBranchName } from "./utils/getSuggestedBranchName";
import { updateGitCacheFromSnapshot } from "./utils/updateGitCache";

export type { GitMenuAction, GitMenuActionId };

interface GitInteractionState {
  primaryAction: GitMenuAction;
  actions: GitMenuAction[];
  hasChanges: boolean;
  aheadOfRemote: number;
  behind: number;
  currentBranch: string | null;
  defaultBranch: string | null;
  isFeatureBranch: boolean;
  prBaseBranch: string | null;
  prHeadBranch: string | null;
  diffStats: DiffStats;
  prUrl: string | null;
  pushDisabledReason: string | null;
  isLoading: boolean;
  stagedFiles: ChangedFile[];
  unstagedFiles: ChangedFile[];
}

interface GitInteractionActions {
  openAction: (actionId: GitMenuActionId) => void;
  closeCommit: () => void;
  closePush: () => void;
  closeBranch: () => void;
  setCommitMessage: (value: string) => void;
  setCommitNextStep: (value: CommitNextStep) => void;
  setCommitAll: (value: boolean) => void;
  setPrTitle: (value: string) => void;
  setPrBody: (value: string) => void;
  setBranchName: (value: string) => void;
  runCommit: () => Promise<boolean>;
  runPush: (mode?: PushMode) => Promise<void>;
  runBranch: () => Promise<boolean>;
  runCreatePr: () => Promise<void>;
  generateCommitMessage: () => Promise<void>;
  generatePrTitleAndBody: () => Promise<void>;
  closeCreatePr: () => void;
  setCreatePrBranchName: (value: string) => void;
  setCreatePrDraft: (value: boolean) => void;
}

export function useGitInteraction(
  taskId: string,
  repoPath?: string,
): {
  state: GitInteractionState;
  modals: GitInteractionStore;
  actions: GitInteractionActions;
} {
  const queryClient = useQueryClient();
  const cacheKeyProvider = useService<GitCacheKeyProvider>(
    GIT_CACHE_KEY_PROVIDER,
  );
  const service = useService<GitInteractionService>(GIT_INTERACTION_SERVICE);
  const trpc = useHostTRPC();
  const store = useGitInteractionStore();
  const { actions: modal } = store;
  const pushAbortRef = useRef<AbortController | null>(null);
  const { isOnline } = useConnectivity();

  const git = useGitQueries(repoPath);

  const computed = useMemo(
    () =>
      computeGitInteractionState({
        repoPath,
        isRepo: git.isRepo,
        isRepoLoading: git.isRepoLoading,
        hasChanges: git.hasChanges,
        aheadOfRemote: git.aheadOfRemote,
        behind: git.behind,
        aheadOfDefault: git.aheadOfDefault,
        hasRemote: git.hasRemote,
        isFeatureBranch: git.isFeatureBranch,
        currentBranch: git.currentBranch,
        defaultBranch: git.defaultBranch,
        ghStatus: git.ghStatus ?? null,
        repoInfo: git.repoInfo ?? null,
        prStatus: git.prStatus ?? null,
        isOnline,
      }),
    [
      repoPath,
      git.isRepo,
      git.isRepoLoading,
      git.hasChanges,
      git.aheadOfRemote,
      git.behind,
      git.aheadOfDefault,
      git.hasRemote,
      git.isFeatureBranch,
      git.currentBranch,
      git.defaultBranch,
      git.ghStatus,
      git.repoInfo,
      git.prStatus,
      isOnline,
    ],
  );

  const { stagedFiles, unstagedFiles } = useMemo(
    () => partitionByStaged(git.changedFiles),
    [git.changedFiles],
  );

  const { stagingContext, stagedOnly } = deriveStagingPlan(
    stagedFiles,
    unstagedFiles,
    store.commitAll,
  );

  const createPrDraftKey = `${taskId}:${repoPath ?? ""}`;

  const openCreatePr = () => {
    const plan = deriveCreatePrPlan({
      isFeatureBranch: git.isFeatureBranch,
      prExists: git.prStatus?.prExists ?? false,
      hasChanges: git.hasChanges,
      stagedFileCount: stagedFiles.length,
      unstagedFileCount: unstagedFiles.length,
    });
    modal.setCommitAll(plan.commitAll);
    modal.openCreatePr({
      needsBranch: plan.needsBranch,
      needsCommit: plan.needsCommit,
      baseBranch: git.currentBranch,
      suggestedBranchName: plan.needsBranch
        ? getSuggestedBranchName(
            queryClient,
            cacheKeyProvider,
            taskId,
            repoPath,
          )
        : undefined,
      draftKey: createPrDraftKey,
    });
  };

  const runCreatePr = async () => {
    if (!repoPath) return;

    if (store.createPrNeedsBranch && !store.branchName.trim()) {
      modal.setCreatePrError("Branch name is required.");
      return;
    }

    modal.setIsSubmitting(true);
    modal.setCreatePrError(null);
    modal.setCreatePrStep("idle");
    modal.setCreatePrFailedStep(null);

    const flowId = crypto.randomUUID();

    try {
      const result = await service.runCreatePr({
        repoPath,
        taskId,
        flowId,
        needsBranch: store.createPrNeedsBranch,
        branchName: store.branchName,
        currentBranch: git.currentBranch,
        commitMessage: store.commitMessage,
        prTitle: store.prTitle,
        prBody: store.prBody,
        draft: store.createPrDraft,
        stagedOnly,
        stagingContext,
        onStep: (step) => {
          if (useGitInteractionStore.getState().createPrStep === step) return;
          modal.setCreatePrStep(step);
        },
      });

      if (result.outcome === "error") {
        useGitInteractionStore.setState({
          createPrError: result.message,
          createPrFailedStep: result.failedStep,
          createPrStep: "error",
        });
        return;
      }

      if (result.snapshot) {
        updateGitCacheFromSnapshot(queryClient, repoPath, result.snapshot);
      }
      if (result.branchInvalidated) {
        invalidateGitBranchQueries(repoPath);
      }
      if (result.prUrl && result.linkedBranchName) {
        queryClient.setQueryData(
          trpc.git.getPrUrlForBranch.queryKey({
            directoryPath: repoPath,
            branchName: result.linkedBranchName,
          }),
          result.prUrl,
        );
      }

      modal.clearCreatePrDraft(createPrDraftKey);
      modal.closeCreatePr();
    } finally {
      modal.setIsSubmitting(false);
    }
  };

  const viewPr = async () => {
    if (!repoPath) return;
    await service.viewPr(repoPath);
  };

  const openAction = (id: GitMenuActionId) => {
    const actionMap: Record<GitMenuActionId, () => void> = {
      commit: () => {
        modal.setCommitAll(
          !(stagedFiles.length > 0 && unstagedFiles.length > 0),
        );
        modal.openCommit("commit");
      },
      push: () => modal.openPush("push"),
      sync: () => modal.openPush("sync"),
      publish: () => modal.openPush("publish"),
      "view-pr": () => viewPr(),
      "create-pr": () => openCreatePr(),
      "branch-here": () =>
        modal.openBranch(
          getSuggestedBranchName(
            queryClient,
            cacheKeyProvider,
            taskId,
            repoPath,
          ),
        ),
    };
    actionMap[id]();
  };

  const runCommit = async (): Promise<boolean> => {
    if (!repoPath) return false;

    modal.setIsSubmitting(true);
    modal.setCommitError(null);

    try {
      const result = await service.runCommit({
        repoPath,
        taskId,
        message: store.commitMessage.trim(),
        stagedOnly,
        stagingContext,
        hasRemote: git.hasRemote,
        pushDisabledReason: computed.pushDisabledReason,
        commitPush: store.commitNextStep === "commit-push",
      });

      if (result.outcome !== "committed") {
        modal.setCommitError(result.message);
        return false;
      }

      if (result.generatedMessage) {
        modal.setCommitMessage(result.generatedMessage);
      }
      if (result.snapshot) {
        updateGitCacheFromSnapshot(queryClient, repoPath, result.snapshot);
      }

      modal.setCommitMessage("");
      modal.closeCommit();

      if (result.next) {
        modal.openPush(result.next.mode);
        applyPushResult(result.next.result);
      }
      return true;
    } finally {
      modal.setIsSubmitting(false);
    }
  };

  const applyPushResult = (
    result: Awaited<ReturnType<GitInteractionService["runPush"]>>,
  ) => {
    if (!repoPath) return;
    if (result.outcome === "aborted") return;
    if (result.outcome === "error") {
      modal.setPushError(result.message);
      modal.setPushState("error");
      return;
    }
    if (result.snapshot) {
      updateGitCacheFromSnapshot(queryClient, repoPath, result.snapshot);
    }
    modal.setPushState("success");
  };

  const runPush = async (mode?: PushMode) => {
    if (!repoPath) return;

    const pushMode = mode ?? useGitInteractionStore.getState().pushMode;

    pushAbortRef.current?.abort();
    const controller = new AbortController();
    pushAbortRef.current = controller;

    modal.setIsSubmitting(true);
    modal.setPushError(null);

    try {
      const result = await service.runPush({
        repoPath,
        taskId,
        mode: pushMode,
        signal: controller.signal,
      });
      applyPushResult(result);
    } finally {
      if (pushAbortRef.current === controller) {
        pushAbortRef.current = null;
      }
      modal.setIsSubmitting(false);
    }
  };

  const closePush = () => {
    pushAbortRef.current?.abort();
    pushAbortRef.current = null;
    modal.closePush();
  };

  const generateCommitMessage = async () => {
    if (!repoPath) return;

    modal.setIsGeneratingCommitMessage(true);
    modal.setCommitError(null);

    try {
      const result = await service.generateCommitMessage(repoPath, taskId);
      if ("message" in result) {
        modal.setCommitMessage(result.message);
      } else {
        modal.setCommitError(result.error);
      }
    } finally {
      modal.setIsGeneratingCommitMessage(false);
    }
  };

  const generatePrTitleAndBody = async () => {
    if (!repoPath) return;

    modal.setIsGeneratingPr(true);
    modal.setCreatePrError(null);

    try {
      const result = await service.generatePrTitleAndBody(repoPath, taskId);
      if ("error" in result) {
        modal.setCreatePrError(result.error);
      } else {
        modal.setPrTitle(result.title);
        modal.setPrBody(result.body);
      }
    } finally {
      modal.setIsGeneratingPr(false);
    }
  };

  const runBranch = async (): Promise<boolean> => {
    if (!repoPath) return false;

    modal.setIsSubmitting(true);
    modal.setBranchError(null);

    try {
      const result = await service.runBranch({
        repoPath,
        taskId,
        rawBranchName: store.branchName,
      });

      if (result.outcome === "error") {
        modal.setBranchError(result.message);
        return false;
      }

      await queryClient.invalidateQueries({ queryKey: WORKSPACE_QUERY_KEY });
      modal.closeBranch();
      return true;
    } finally {
      modal.setIsSubmitting(false);
    }
  };

  return {
    state: {
      primaryAction: computed.primaryAction,
      actions: computed.actions,
      hasChanges: git.hasChanges,
      aheadOfRemote: git.aheadOfRemote,
      behind: git.behind,
      currentBranch: git.currentBranch,
      defaultBranch: git.defaultBranch,
      isFeatureBranch: git.isFeatureBranch,
      prBaseBranch: computed.prBaseBranch,
      prHeadBranch: computed.prHeadBranch,
      diffStats: git.diffStats,
      prUrl: computed.prUrl,
      pushDisabledReason: computed.pushDisabledReason,
      isLoading: git.isLoading,
      stagedFiles,
      unstagedFiles,
    },
    modals: store,
    actions: {
      openAction,
      closeCommit: modal.closeCommit,
      closePush,
      closeBranch: modal.closeBranch,
      setCommitMessage: modal.setCommitMessage,
      setCommitNextStep: modal.setCommitNextStep,
      setCommitAll: modal.setCommitAll,
      setPrTitle: modal.setPrTitle,
      setPrBody: modal.setPrBody,
      setBranchName: (value: string) => {
        const { sanitized, error } = getBranchNameInputState(value);
        modal.setBranchName(sanitized);
        modal.setBranchError(error);
      },
      runCommit,
      runPush,
      runBranch,
      runCreatePr,
      generateCommitMessage,
      generatePrTitleAndBody,
      closeCreatePr: modal.closeCreatePr,
      setCreatePrBranchName: (value: string) => {
        const sanitized = sanitizeBranchName(value);
        modal.setBranchName(sanitized);
      },
      setCreatePrDraft: modal.setCreatePrDraft,
    },
  };
}
