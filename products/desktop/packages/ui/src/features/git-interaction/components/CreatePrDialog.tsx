import { GitPullRequest } from "@phosphor-icons/react";
import {
  type DiffStats,
  formatFileCountLabel,
} from "@posthog/core/git-interaction/diffStats";
import { buildCreatePrFlowErrorPrompt } from "@posthog/core/git-interaction/errorPrompts";
import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Text,
  Textarea,
} from "@posthog/quill";
import { StepList, type StepStatus } from "../../../primitives/StepList";
import { useGitInteractionStore } from "../state/gitInteractionStore";
import type { CreatePrStep } from "../types";
import { useFixWithAgent } from "../useFixWithAgent";
import {
  CommitAllToggle,
  ErrorContainer,
  GenerateButton,
} from "./GitInteractionDialogs";

const ICON_SIZE = 14;

const STEP_ORDER: CreatePrStep[] = [
  "creating-branch",
  "committing",
  "pushing",
  "creating-pr",
  "complete",
];

function resolveStepStatus(
  stepId: CreatePrStep,
  currentStep: CreatePrStep,
  failedStep: CreatePrStep | null | undefined,
): StepStatus {
  const currentIndex = STEP_ORDER.indexOf(currentStep);
  const stepIndex = STEP_ORDER.indexOf(stepId);
  if (currentStep === "error" && stepId === failedStep) return "failed";
  if (currentStep === "complete" || stepIndex < currentIndex)
    return "completed";
  if (stepId === currentStep) return "in_progress";
  return "pending";
}

interface StepDef {
  id: CreatePrStep;
  label: string;
}

export interface CreatePrDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentBranch: string | null;
  diffStats: DiffStats;
  isSubmitting: boolean;
  onSubmit: () => void;
  onGenerateCommitMessage: () => void;
  onGeneratePr: () => void;
  showCommitAllToggle?: boolean;
  commitAll?: boolean;
  onCommitAllChange?: (value: boolean) => void;
  stagedFileCount?: number;
}

export function CreatePrDialog({
  open,
  onOpenChange,
  currentBranch,
  diffStats,
  isSubmitting,
  onSubmit,
  onGenerateCommitMessage,
  onGeneratePr,
  showCommitAllToggle,
  commitAll,
  onCommitAllChange,
  stagedFileCount,
}: CreatePrDialogProps) {
  const store = useGitInteractionStore();
  const { actions } = store;
  const { canFixWithAgent, fixWithAgent } = useFixWithAgent(() =>
    buildCreatePrFlowErrorPrompt(store.createPrFailedStep),
  );

  const { createPrStep: step } = store;
  const isExecuting = step !== "idle" && step !== "complete";

  // Build the step list based on what's needed
  const steps: StepDef[] = [];
  if (store.createPrNeedsBranch) {
    steps.push({
      id: "creating-branch",
      label: `Create branch ${store.branchName || ""}`.trim(),
    });
  }
  if (store.createPrNeedsCommit) {
    steps.push({ id: "committing", label: "Commit changes" });
  }
  steps.push({ id: "pushing", label: "Push to remote" });
  steps.push({ id: "creating-pr", label: "Create pull request" });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitPullRequest size={ICON_SIZE} />
            {isExecuting ? "Creating PR..." : "Create PR"}
          </DialogTitle>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-3">
          {!isExecuting && (
            <>
              {store.createPrNeedsBranch && (
                <div className="flex flex-col gap-1">
                  <Text size="xs" variant="muted">
                    Branch
                  </Text>
                  <Input
                    value={store.branchName}
                    onChange={(event) =>
                      actions.setBranchName(event.target.value)
                    }
                    placeholder="branch-name"
                    autoFocus
                  />
                  {currentBranch && (
                    <Text size="xs" variant="muted">
                      from {currentBranch}
                    </Text>
                  )}
                </div>
              )}

              {store.createPrNeedsCommit && (
                <div className="flex flex-col gap-1">
                  <div className="flex items-center justify-between">
                    <Text size="xs" variant="muted">
                      Commit message
                    </Text>
                    <div className="flex items-center gap-2">
                      <Text size="xs" variant="muted">
                        {formatFileCountLabel(
                          !!(showCommitAllToggle && !commitAll),
                          stagedFileCount ?? 0,
                          diffStats.filesChanged,
                        )}
                      </Text>
                      <Text size="xs" className="text-(--green-11)">
                        +{diffStats.linesAdded}
                      </Text>
                      <Text size="xs" variant="destructive">
                        -{diffStats.linesRemoved}
                      </Text>
                      <GenerateButton
                        onClick={onGenerateCommitMessage}
                        isGenerating={store.isGeneratingCommitMessage}
                      />
                    </div>
                  </div>
                  <Textarea
                    value={store.commitMessage}
                    onChange={(event) =>
                      actions.setCommitMessage(event.target.value)
                    }
                    placeholder="Leave empty to generate"
                    rows={1}
                    disabled={store.isGeneratingCommitMessage}
                    autoFocus={!store.createPrNeedsBranch}
                  />
                  {showCommitAllToggle && onCommitAllChange && (
                    <CommitAllToggle
                      checked={commitAll}
                      onChange={onCommitAllChange}
                    />
                  )}
                </div>
              )}

              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <Text size="xs" variant="muted">
                    PR title
                  </Text>
                  <GenerateButton
                    onClick={onGeneratePr}
                    isGenerating={store.isGeneratingPr}
                  />
                </div>
                <Input
                  value={store.prTitle}
                  onChange={(event) => actions.setPrTitle(event.target.value)}
                  placeholder="Leave empty to generate"
                  disabled={store.isGeneratingPr}
                  autoFocus={
                    !store.createPrNeedsBranch && !store.createPrNeedsCommit
                  }
                />
              </div>

              <div className="flex flex-col gap-1">
                <Text size="xs" variant="muted">
                  Description
                </Text>
                <Textarea
                  value={store.prBody}
                  onChange={(event) => actions.setPrBody(event.target.value)}
                  placeholder="Leave empty to generate"
                  rows={4}
                  disabled={store.isGeneratingPr}
                />
              </div>

              <div className="flex items-center gap-2">
                <Checkbox
                  id="create-pr-draft"
                  size="sm"
                  checked={store.createPrDraft}
                  onCheckedChange={(checked) =>
                    actions.setCreatePrDraft(checked === true)
                  }
                />
                <Label
                  htmlFor="create-pr-draft"
                  className="text-muted-foreground text-xs"
                >
                  Create as draft
                </Label>
              </div>

              {store.createPrError && (
                <ErrorContainer error={store.createPrError} />
              )}
            </>
          )}

          {isExecuting && (
            <>
              <StepList
                steps={steps.map((stepDefinition) => ({
                  key: stepDefinition.id,
                  label: stepDefinition.label,
                  status: resolveStepStatus(
                    stepDefinition.id,
                    step,
                    store.createPrFailedStep,
                  ),
                }))}
                gap="3"
              />

              {step === "error" && store.createPrError && (
                <ErrorContainer
                  error={store.createPrError}
                  onFixWithAgent={
                    canFixWithAgent
                      ? () => {
                          fixWithAgent(store.createPrError ?? "");
                          actions.closeCreatePr();
                        }
                      : undefined
                  }
                />
              )}
            </>
          )}
        </DialogBody>

        <DialogFooter>
          <DialogClose render={<Button size="sm" variant="outline" />}>
            {isExecuting && step === "error" ? "Close" : "Cancel"}
          </DialogClose>
          {!isExecuting && (
            <Button
              size="sm"
              variant="primary"
              disabled={isSubmitting}
              loading={isSubmitting}
              onClick={onSubmit}
            >
              Create PR
            </Button>
          )}
          {isExecuting && step === "error" && (
            <Button
              size="sm"
              variant="primary"
              disabled={isSubmitting}
              loading={isSubmitting}
              onClick={onSubmit}
            >
              Retry
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
