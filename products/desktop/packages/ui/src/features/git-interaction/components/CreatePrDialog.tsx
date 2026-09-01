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
  Flex,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
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
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="500px" size="1">
        <Flex direction="column" gap="3">
          <Flex align="center" gap="2">
            <GitPullRequest size={ICON_SIZE} />
            <Text className="font-medium text-sm">
              {isExecuting ? "Creating PR..." : "Create PR"}
            </Text>
          </Flex>

          {!isExecuting && (
            <>
              {store.createPrNeedsBranch && (
                <Flex direction="column" gap="1">
                  <Text color="gray" className="text-[13px]">
                    Branch
                  </Text>
                  <TextField.Root
                    value={store.branchName}
                    onChange={(e) => actions.setBranchName(e.target.value)}
                    placeholder="branch-name"
                    size="1"
                    autoFocus
                  />
                  {currentBranch && (
                    <Text color="gray" className="text-[13px]">
                      from {currentBranch}
                    </Text>
                  )}
                </Flex>
              )}

              {store.createPrNeedsCommit && (
                <Flex direction="column" gap="1">
                  <Flex align="center" justify="between">
                    <Text color="gray" className="text-[13px]">
                      Commit message
                    </Text>
                    <Flex align="center" gap="2">
                      <Text color="gray" className="text-[13px]">
                        {formatFileCountLabel(
                          !!(showCommitAllToggle && !commitAll),
                          stagedFileCount ?? 0,
                          diffStats.filesChanged,
                        )}
                      </Text>
                      <Text color="green" className="text-[13px]">
                        +{diffStats.linesAdded}
                      </Text>
                      <Text color="red" className="text-[13px]">
                        -{diffStats.linesRemoved}
                      </Text>
                      <GenerateButton
                        onClick={onGenerateCommitMessage}
                        isGenerating={store.isGeneratingCommitMessage}
                      />
                    </Flex>
                  </Flex>
                  <TextArea
                    value={store.commitMessage}
                    onChange={(e) => actions.setCommitMessage(e.target.value)}
                    placeholder="Leave empty to generate"
                    size="1"
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
                </Flex>
              )}

              <Flex direction="column" gap="1">
                <Flex align="center" justify="between">
                  <Text color="gray" className="text-[13px]">
                    PR title
                  </Text>
                  <GenerateButton
                    onClick={onGeneratePr}
                    isGenerating={store.isGeneratingPr}
                  />
                </Flex>
                <TextField.Root
                  value={store.prTitle}
                  onChange={(e) => actions.setPrTitle(e.target.value)}
                  placeholder="Leave empty to generate"
                  size="1"
                  disabled={store.isGeneratingPr}
                  autoFocus={
                    !store.createPrNeedsBranch && !store.createPrNeedsCommit
                  }
                />
              </Flex>

              <Flex direction="column" gap="1">
                <Text color="gray" className="text-[13px]">
                  Description
                </Text>
                <TextArea
                  value={store.prBody}
                  onChange={(e) => actions.setPrBody(e.target.value)}
                  placeholder="Leave empty to generate"
                  size="1"
                  rows={4}
                  disabled={store.isGeneratingPr}
                />
              </Flex>

              <Text as="label" color="gray" className="text-[13px]">
                <Flex gap="2" align="center">
                  <Checkbox
                    size="1"
                    checked={store.createPrDraft}
                    onCheckedChange={(checked) =>
                      actions.setCreatePrDraft(checked === true)
                    }
                  />
                  Create as draft
                </Flex>
              </Text>

              {store.createPrError && (
                <ErrorContainer error={store.createPrError} />
              )}

              <Flex gap="2" justify="end">
                <Dialog.Close>
                  <Button size="1" variant="soft" color="gray">
                    Cancel
                  </Button>
                </Dialog.Close>
                <Button
                  size="1"
                  disabled={isSubmitting}
                  loading={isSubmitting}
                  onClick={onSubmit}
                >
                  Create PR
                </Button>
              </Flex>
            </>
          )}

          {isExecuting && (
            <>
              <StepList
                steps={steps.map((s) => ({
                  key: s.id,
                  label: s.label,
                  status: resolveStepStatus(
                    s.id,
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

              <Flex gap="2" justify="end">
                <Dialog.Close>
                  <Button size="1" variant="soft" color="gray">
                    {step === "error" ? "Close" : "Cancel"}
                  </Button>
                </Dialog.Close>
                {step === "error" && (
                  <Button size="1" onClick={onSubmit}>
                    Retry
                  </Button>
                )}
              </Flex>
            </>
          )}
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
