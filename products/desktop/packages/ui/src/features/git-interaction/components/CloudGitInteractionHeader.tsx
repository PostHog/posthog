import { Laptop, Spinner } from "@phosphor-icons/react";
import type { ContinueAfterDirtyTreeStep } from "@posthog/core/sessions/localHandoffService";
import { useService } from "@posthog/di/react";
import { Button as QuillButton } from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import {
  LOCAL_HANDOFF_SERVICE,
  type LocalHandoffService,
} from "@posthog/ui/features/sessions/localHandoffService";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useHostCapabilities } from "../../../shell/useHostCapabilities";
import { useFeatureFlag } from "../../feature-flags/useFeatureFlag";
import { DirtyTreeDialog } from "../../sessions/components/DirtyTreeDialog";
import { HandoffConfirmDialog } from "../../sessions/components/HandoffConfirmDialog";
import { useHandoffDialogStore } from "../../sessions/handoffDialogStore";
import { useSessionForTask } from "../../sessions/useSession";
import {
  GIT_CACHE_KEY_PROVIDER,
  type GitCacheKeyProvider,
} from "../gitCacheProvider";
import { useGitInteractionStore } from "../state/gitInteractionStore";
import { useGitInteraction } from "../useGitInteraction";
import { getSuggestedBranchName } from "../utils/getSuggestedBranchName";
import { GitBranchDialog, GitCommitDialog } from "./GitInteractionDialogs";

const CLOUD_HANDOFF_FLAG = "phc-cloud-handoff";

interface CloudGitInteractionHeaderProps {
  taskId: string;
  task: Task;
}

export function CloudGitInteractionHeader({
  taskId,
  task,
}: CloudGitInteractionHeaderProps) {
  const session = useSessionForTask(taskId);
  const queryClient = useQueryClient();
  const cacheKeyProvider = useService<GitCacheKeyProvider>(
    GIT_CACHE_KEY_PROVIDER,
  );
  const localHandoff = useService<LocalHandoffService>(LOCAL_HANDOFF_SERVICE);
  const { localWorkspaces } = useHostCapabilities();
  const cloudHandoffEnabled =
    useFeatureFlag(CLOUD_HANDOFF_FLAG) || import.meta.env.DEV;

  const confirmOpen = useHandoffDialogStore((s) => s.confirmOpen);
  const direction = useHandoffDialogStore((s) => s.direction);
  const branchName = useHandoffDialogStore((s) => s.branchName);
  const dirtyTreeOpen = useHandoffDialogStore((s) => s.dirtyTreeOpen);
  const changedFiles = useHandoffDialogStore((s) => s.changedFiles);
  const closeConfirm = useHandoffDialogStore((s) => s.closeConfirm);
  const pendingAfterCommit = useHandoffDialogStore((s) => s.pendingAfterCommit);

  const commitRepoPath = pendingAfterCommit?.repoPath;
  const git = useGitInteraction(taskId, commitRepoPath);

  const [isPreflighting, setIsPreflighting] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setPreflightError(null);
    setIsPreflighting(true);
    try {
      await localHandoff.start(taskId, task);
    } catch (err) {
      setPreflightError(
        err instanceof Error ? err.message : "Preflight failed",
      );
    } finally {
      setIsPreflighting(false);
    }
  };

  const applyStep = (step: ContinueAfterDirtyTreeStep) => {
    const actions = useGitInteractionStore.getState().actions;
    if (step.step === "open-commit") {
      actions.openCommit("commit");
      return;
    }
    actions.openBranch(step.suggestedName);
  };

  const handleCommitAndContinue = async () => {
    applyStep(
      localHandoff.continueAfterDirtyTree({
        isFeatureBranch: git.state.isFeatureBranch,
        suggestedBranchName: getSuggestedBranchName(
          queryClient,
          cacheKeyProvider,
          taskId,
          commitRepoPath,
        ),
      }),
    );
  };

  const handleBranchConfirm = async () => {
    const branchCreated = await git.actions.runBranch();
    if (!branchCreated) return;
    applyStep(localHandoff.afterBranchCreated());
  };

  const handleCommitConfirm = async () => {
    const committed = await git.actions.runCommit();
    if (!committed) return;
    await localHandoff.afterCommit();
  };

  // "Continue locally" hands the task off to a local checkout
  if (!cloudHandoffEnabled || !localWorkspaces) return null;
  if (task.origin_product === "image_builder") return null;

  const inProgress = session?.handoffInProgress ?? false;

  return (
    <>
      <div className="no-drag flex items-center">
        <QuillButton
          variant="outline"
          size="sm"
          disabled={inProgress}
          onClick={() =>
            localHandoff.openConfirm(taskId, session?.cloudBranch ?? null)
          }
        >
          {inProgress ? (
            <Spinner size={14} className="shrink-0 animate-spin" />
          ) : (
            <Laptop size={14} weight="regular" className="shrink-0" />
          )}
          {inProgress ? "Transferring..." : "Continue locally"}
        </QuillButton>
      </div>
      {confirmOpen && direction === "to-local" && (
        <HandoffConfirmDialog
          open={confirmOpen}
          onOpenChange={(open) => {
            if (!open) {
              closeConfirm();
              setPreflightError(null);
            }
          }}
          direction="to-local"
          branchName={branchName}
          onConfirm={handleConfirm}
          isSubmitting={isPreflighting}
          error={preflightError}
        />
      )}
      {dirtyTreeOpen && (
        <DirtyTreeDialog
          open={dirtyTreeOpen}
          onOpenChange={(open) => {
            if (!open) localHandoff.cancelPendingFlow();
          }}
          changedFiles={changedFiles}
          onCommitAndContinue={handleCommitAndContinue}
        />
      )}
      {pendingAfterCommit && (
        <GitCommitDialog
          open={git.modals.commitOpen}
          onOpenChange={(open) => {
            if (!open) {
              git.actions.closeCommit();
              localHandoff.cancelPendingFlow();
            }
          }}
          branchName={git.state.currentBranch ?? pendingAfterCommit.branchName}
          diffStats={git.state.diffStats}
          commitMessage={git.modals.commitMessage}
          onCommitMessageChange={git.actions.setCommitMessage}
          nextStep={git.modals.commitNextStep}
          onNextStepChange={git.actions.setCommitNextStep}
          pushDisabledReason={git.state.pushDisabledReason}
          onContinue={handleCommitConfirm}
          isSubmitting={git.modals.isSubmitting}
          error={git.modals.commitError}
          onGenerateMessage={git.actions.generateCommitMessage}
          isGeneratingMessage={git.modals.isGeneratingCommitMessage}
          showCommitAllToggle={
            git.state.stagedFiles.length > 0 &&
            git.state.unstagedFiles.length > 0
          }
          commitAll={git.modals.commitAll}
          onCommitAllChange={git.actions.setCommitAll}
          stagedFileCount={git.state.stagedFiles.length}
        />
      )}
      {pendingAfterCommit && (
        <GitBranchDialog
          open={git.modals.branchOpen}
          onOpenChange={(open) => {
            if (!open) {
              git.actions.closeBranch();
              localHandoff.cancelPendingFlow();
            }
          }}
          branchName={git.modals.branchName}
          onBranchNameChange={git.actions.setBranchName}
          onConfirm={handleBranchConfirm}
          isSubmitting={git.modals.isSubmitting}
          error={git.modals.branchError}
        />
      )}
    </>
  );
}
