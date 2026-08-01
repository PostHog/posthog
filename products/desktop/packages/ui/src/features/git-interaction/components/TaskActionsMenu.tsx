import {
  ArrowsClockwise,
  CloudArrowUp,
  Copy,
  Eye,
  GitBranch,
  GitCommit,
  GitFork,
  GitPullRequest,
} from "@phosphor-icons/react";
import { getPrVisualConfig } from "@posthog/core/git-interaction/prStatus";
import { parseGithubUrl } from "@posthog/git/utils";
import {
  ButtonGroup,
  DropdownMenuContent,
  DropdownMenuTrigger,
  Button as QButton,
  DropdownMenu as QDropdownMenu,
  DropdownMenuItem as QDropdownMenuItem,
} from "@posthog/quill";
import type { PrActionType } from "@posthog/shared";
import { ChevronDownIcon } from "@radix-ui/react-icons";
import { Button, DropdownMenu, Flex, Spinner, Text } from "@radix-ui/themes";
import { ChevronDown } from "lucide-react";
import { Tooltip } from "../../../primitives/Tooltip";
import { toast } from "../../../primitives/toast";
import { useLocalRepoPath } from "../../workspace/useLocalRepoPath";
import { getPrActionIcon, getPrVisualIcon } from "../prIcon";
import { useCloudPrSummaries, useCloudPrUrls } from "../useCloudPrUrl";
import {
  type GitMenuAction,
  type GitMenuActionId,
  useGitInteraction,
} from "../useGitInteraction";
import { usePrActions } from "../usePrActions";
import {
  type PrStateDetails,
  usePrDetails,
  usePrDetailsMap,
} from "../usePrDetails";
import { usePrSummaryBackfill } from "../usePrSummaryBackfill";
import { useSetPrimaryPr } from "../useSetPrimaryPr";
import { useTaskPrUrls } from "../useTaskPrUrl";
import { CreatePrDialog } from "./CreatePrDialog";
import {
  GitBranchDialog,
  GitCommitDialog,
  GitPushDialog,
} from "./GitInteractionDialogs";
import { PRBadgeLink } from "./PRBadgeLink";

interface TaskActionsMenuProps {
  taskId: string;
  isCloud: boolean;
}

// Work-shipping slots flip to disabled solely to signal "nothing to do" (no
// changes, branch up to date, no commits to publish). Next to a PR badge that
// noise isn't useful, so we drop them when a PR exists. Other disabled
// actions stay visible so their `disabledReason` tooltip can still explain
// why they're unavailable.
const NO_WORK_SLOTS = new Set<GitMenuActionId>([
  "commit",
  "push",
  "sync",
  "publish",
]);

/**
 * Unified actions control shown in the task header. Combines:
 *   - Git interaction (commit/push/create-PR/branch) for local tasks
 *   - PR status badge + PR lifecycle actions (close/draft/ready) for any task
 *     whose branch has a PR
 *
 * Trigger is the PR badge when a PR exists (click → GitHub), otherwise the
 * primary git action button (click → execute). Chevron opens the full action
 * list. Cloud tasks without a PR render nothing.
 */
export function TaskActionsMenu({ taskId, isCloud }: TaskActionsMenuProps) {
  // Git state (skipped for cloud — useGitInteraction handles undefined repo).
  const localRepoPath = useLocalRepoPath(taskId);
  const {
    state: gitState,
    modals,
    actions: gitActions,
  } = useGitInteraction(taskId, isCloud ? undefined : localRepoPath);

  const { primaryUrl: prUrl, otherUrls } = useTaskPrUrls(taskId, isCloud);
  const cloudPrUrls = useCloudPrUrls(taskId);
  const prSummaries = useCloudPrSummaries(taskId);
  const { mutate: setPrimaryPr } = useSetPrimaryPr(taskId);
  usePrSummaryBackfill(taskId, cloudPrUrls, otherUrls.length > 0, prSummaries);
  const otherPrDetails = usePrDetailsMap(otherUrls);

  const {
    meta: { state: prState, merged, draft, headRefName },
  } = usePrDetails(prUrl);
  const { execute: executePrAction, isPending: isPrActionPending } =
    usePrActions(prUrl);

  const pr = prUrl && prState !== null ? { url: prUrl, state: prState } : null;

  // Cloud tasks only appear when they have a PR.
  if (isCloud && !pr) return null;

  // When a PR exists the badge handles "view PR" and "create PR" is moot.
  const gitItems = isCloud
    ? []
    : gitState.actions.filter((a) => {
        if (!pr) return true;
        if (a.id === "view-pr" || a.id === "create-pr") return false;
        if (!a.enabled && NO_WORK_SLOTS.has(a.id)) return false;
        return true;
      });

  return (
    <>
      <div className="no-drag">
        {pr ? (
          <PrBadgeControl
            prUrl={pr.url}
            prState={pr.state}
            merged={merged}
            draft={draft}
            branchName={headRefName}
            otherPrs={buildOtherPrItems(
              pr.url,
              otherUrls,
              prSummaries,
              otherPrDetails,
            )}
            isPrPending={isPrActionPending}
            gitItems={gitItems}
            onGitSelect={gitActions.openAction}
            onPrSelect={executePrAction}
            onOtherPrSelect={setPrimaryPr}
          />
        ) : (
          <GitActionControl
            primaryAction={gitState.primaryAction}
            actions={gitItems}
            isBusy={modals.isSubmitting}
            onSelect={gitActions.openAction}
          />
        )}
      </div>

      {!isCloud && (
        <>
          <GitCommitDialog
            open={modals.commitOpen}
            onOpenChange={(open) => {
              if (!open) gitActions.closeCommit();
            }}
            branchName={gitState.currentBranch}
            diffStats={gitState.diffStats}
            commitMessage={modals.commitMessage}
            onCommitMessageChange={gitActions.setCommitMessage}
            nextStep={modals.commitNextStep}
            onNextStepChange={gitActions.setCommitNextStep}
            pushDisabledReason={gitState.pushDisabledReason}
            onContinue={gitActions.runCommit}
            isSubmitting={modals.isSubmitting}
            error={modals.commitError}
            onGenerateMessage={gitActions.generateCommitMessage}
            isGeneratingMessage={modals.isGeneratingCommitMessage}
            showCommitAllToggle={
              gitState.stagedFiles.length > 0 &&
              gitState.unstagedFiles.length > 0
            }
            commitAll={modals.commitAll}
            onCommitAllChange={gitActions.setCommitAll}
            stagedFileCount={gitState.stagedFiles.length}
          />

          <GitPushDialog
            open={modals.pushOpen}
            onOpenChange={(open) => {
              if (!open) gitActions.closePush();
            }}
            branchName={gitState.currentBranch}
            mode={modals.pushMode}
            state={modals.pushState}
            error={modals.pushError}
            onConfirm={gitActions.runPush}
            onClose={gitActions.closePush}
            isSubmitting={modals.isSubmitting}
          />

          <CreatePrDialog
            open={modals.createPrOpen}
            onOpenChange={(open) => {
              if (!open) gitActions.closeCreatePr();
            }}
            currentBranch={modals.createPrBaseBranch}
            diffStats={gitState.diffStats}
            isSubmitting={modals.isSubmitting}
            onSubmit={gitActions.runCreatePr}
            onGenerateCommitMessage={gitActions.generateCommitMessage}
            onGeneratePr={gitActions.generatePrTitleAndBody}
            showCommitAllToggle={
              gitState.stagedFiles.length > 0 &&
              gitState.unstagedFiles.length > 0
            }
            commitAll={modals.commitAll}
            onCommitAllChange={gitActions.setCommitAll}
            stagedFileCount={gitState.stagedFiles.length}
          />

          <GitBranchDialog
            open={modals.branchOpen}
            onOpenChange={(open) => {
              if (!open) gitActions.closeBranch();
            }}
            branchName={modals.branchName}
            onBranchNameChange={gitActions.setBranchName}
            onConfirm={gitActions.runBranch}
            isSubmitting={modals.isSubmitting}
            error={modals.branchError}
          />
        </>
      )}
    </>
  );
}

// --- Trigger when a PR exists: colored badge link + combined dropdown ---

interface OtherPrItem {
  url: string;
  label: string;
  summary: string | null;
  repoLabel: string | null;
  visual: ReturnType<typeof getPrVisualConfig> | null;
}

function buildOtherPrItems(
  primaryUrl: string,
  otherUrls: string[],
  summaries: Record<string, string>,
  details: Record<string, PrStateDetails>,
): OtherPrItem[] {
  const primary = parseGithubUrl(primaryUrl);
  return otherUrls.map((url) => {
    const parsed = parseGithubUrl(url);
    const sameRepo =
      !!parsed &&
      !!primary &&
      parsed.owner.toLowerCase() === primary.owner.toLowerCase() &&
      parsed.repo.toLowerCase() === primary.repo.toLowerCase();
    const detail = details[url];
    return {
      url,
      label: parsed?.kind === "pr" ? `#${parsed.number}` : url,
      summary: summaries[url] ?? null,
      repoLabel: parsed && !sameRepo ? `${parsed.owner}/${parsed.repo}` : null,
      visual: detail
        ? getPrVisualConfig(detail.state, detail.merged, detail.draft)
        : null,
    };
  });
}

interface PrBadgeControlProps {
  prUrl: string;
  prState: string;
  merged: boolean;
  draft: boolean;
  branchName: string | null;
  otherPrs: OtherPrItem[];
  isPrPending: boolean;
  gitItems: GitMenuAction[];
  onGitSelect: (id: GitMenuActionId) => void;
  onPrSelect: (action: PrActionType) => void;
  onOtherPrSelect: (url: string) => void;
}

function PrBadgeControl({
  prUrl,
  prState,
  merged,
  draft,
  branchName,
  otherPrs,
  isPrPending,
  gitItems,
  onGitSelect,
  onPrSelect,
  onOtherPrSelect,
}: PrBadgeControlProps) {
  const config = getPrVisualConfig(prState, merged, draft);
  const lifecycleItems = config.actions;
  const hasMenuItems = gitItems.length + lifecycleItems.length > 0;
  const hasDropdown = hasMenuItems || !!branchName || otherPrs.length > 0;

  const copyBranchName = async () => {
    if (!branchName) return;
    try {
      await navigator.clipboard.writeText(branchName);
      toast.success("Branch name copied");
    } catch {
      toast.error("Couldn't copy branch name");
    }
  };

  return (
    <Flex align="center" gap="0">
      <PRBadgeLink
        prUrl={prUrl}
        prState={prState}
        merged={merged}
        draft={draft}
        isPrPending={isPrPending}
        attachedRight={hasDropdown}
      />
      {hasDropdown && (
        <DropdownMenu.Root>
          <DropdownMenu.Trigger>
            <Button
              size="1"
              variant="soft"
              color={config.color}
              disabled={isPrPending}
              style={{
                borderTopLeftRadius: 0,
                borderBottomLeftRadius: 0,
                borderLeft: `1px solid var(--${config.color}-6)`,
                paddingLeft: "6px",
                paddingRight: "6px",
              }}
            >
              <ChevronDownIcon />
            </Button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Content size="1" align="end">
            {gitItems.map((item) => (
              <GitDropdownItem
                key={item.id}
                action={item}
                onSelect={onGitSelect}
                renderAs="radix"
              />
            ))}
            {gitItems.length > 0 && lifecycleItems.length > 0 && (
              <DropdownMenu.Separator />
            )}
            {lifecycleItems.map((action) => (
              <DropdownMenu.Item
                key={action.id}
                onSelect={() => onPrSelect(action.id)}
              >
                <Flex align="center" gap="2">
                  {getPrActionIcon(action.id)}
                  <Text size="1">{action.label}</Text>
                </Flex>
              </DropdownMenu.Item>
            ))}
            {otherPrs.length > 0 && (
              <>
                {hasMenuItems && <DropdownMenu.Separator />}
                <DropdownMenu.Sub>
                  <DropdownMenu.SubTrigger>
                    <Flex align="center" gap="2">
                      <GitPullRequest size={12} weight="bold" />
                      <Text size="1">Other PRs</Text>
                    </Flex>
                  </DropdownMenu.SubTrigger>
                  <DropdownMenu.SubContent>
                    {otherPrs.map((otherPr) => (
                      <DropdownMenu.Item
                        key={otherPr.url}
                        onSelect={() => onOtherPrSelect(otherPr.url)}
                      >
                        <Flex align="center" gap="2">
                          <OtherPrStateIcon visual={otherPr.visual} />
                          <Text size="1">
                            {otherPr.label}
                            {otherPr.summary && <Text> {otherPr.summary}</Text>}
                            {otherPr.visual && (
                              <Text color={otherPr.visual.color}>
                                {" "}
                                · {otherPr.visual.label}
                              </Text>
                            )}
                            {otherPr.repoLabel && (
                              <Text color="gray"> · {otherPr.repoLabel}</Text>
                            )}
                          </Text>
                        </Flex>
                      </DropdownMenu.Item>
                    ))}
                  </DropdownMenu.SubContent>
                </DropdownMenu.Sub>
              </>
            )}
            {branchName && (
              <>
                {(hasMenuItems || otherPrs.length > 0) && (
                  <DropdownMenu.Separator />
                )}
                <DropdownMenu.Item onSelect={copyBranchName}>
                  <Flex align="center" gap="2">
                    <Copy size={12} weight="bold" />
                    <Text size="1">Copy branch name</Text>
                  </Flex>
                </DropdownMenu.Item>
              </>
            )}
          </DropdownMenu.Content>
        </DropdownMenu.Root>
      )}
    </Flex>
  );
}

function OtherPrStateIcon({ visual }: { visual: OtherPrItem["visual"] }) {
  if (!visual) return <GitPullRequest size={12} weight="bold" />;
  const StateIcon = getPrVisualIcon(visual.icon);
  return (
    <StateIcon size={12} weight="bold" color={`var(--${visual.color}-9)`} />
  );
}

// --- Trigger when no PR: solid primary git action + git dropdown ---

interface GitActionControlProps {
  primaryAction: GitMenuAction;
  actions: GitMenuAction[];
  isBusy: boolean;
  onSelect: (id: GitMenuActionId) => void;
}

function GitActionControl({
  primaryAction,
  actions,
  isBusy,
  onSelect,
}: GitActionControlProps) {
  const allDisabled = actions.every((a) => !a.enabled);
  const showDropdown = actions.length > 1;
  const variant = allDisabled ? "default" : "primary";
  const isPrimaryDisabled = !primaryAction.enabled || isBusy;

  const primaryButton = (
    <QButton
      variant={variant}
      disabled={isPrimaryDisabled}
      onClick={() => onSelect(primaryAction.id)}
      className="bg-primary text-primary-foreground not-disabled:hover:bg-primary/80 hover:text-primary-foreground/80"
    >
      {isBusy ? <Spinner size="1" /> : getGitActionIcon(primaryAction.id)}
      {primaryAction.label}
    </QButton>
  );

  const wrappedPrimaryButton =
    !primaryAction.enabled && primaryAction.disabledReason ? (
      <Tooltip content={primaryAction.disabledReason} side="bottom">
        <span style={{ display: "inline-flex" }}>{primaryButton}</span>
      </Tooltip>
    ) : (
      primaryButton
    );

  if (!showDropdown || allDisabled) {
    return wrappedPrimaryButton;
  }

  return (
    <ButtonGroup>
      {wrappedPrimaryButton}
      <QDropdownMenu>
        <DropdownMenuTrigger
          render={
            <QButton
              className="bg-primary not-disabled:hover:bg-primary/80"
              variant={variant}
              disabled={isBusy}
            />
          }
        >
          <ChevronDown size={12} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {actions.map((action) => (
            <GitDropdownItem
              key={action.id}
              action={action}
              onSelect={onSelect}
              renderAs="quill"
            />
          ))}
        </DropdownMenuContent>
      </QDropdownMenu>
    </ButtonGroup>
  );
}

// --- Shared dropdown item for git actions (rendered in either menu kind) ---

function GitDropdownItem({
  action,
  onSelect,
  renderAs,
}: {
  action: GitMenuAction;
  onSelect: (id: GitMenuActionId) => void;
  renderAs: "quill" | "radix";
}) {
  const icon = getGitActionIcon(action.id);
  const label = action.label;

  if (renderAs === "radix") {
    const item = (
      <DropdownMenu.Item
        disabled={!action.enabled}
        onSelect={() => onSelect(action.id)}
      >
        <Flex align="center" gap="2">
          {icon}
          <Text size="1">{label}</Text>
        </Flex>
      </DropdownMenu.Item>
    );
    return !action.enabled && action.disabledReason ? (
      <Tooltip content={action.disabledReason} side="left">
        <span>{item}</span>
      </Tooltip>
    ) : (
      item
    );
  }

  const itemContent = (
    <>
      {icon} {label}
    </>
  );
  if (!action.enabled && action.disabledReason) {
    return (
      <Tooltip content={action.disabledReason} side="left">
        <QDropdownMenuItem disabled>{itemContent}</QDropdownMenuItem>
      </Tooltip>
    );
  }
  return (
    <QDropdownMenuItem onClick={() => onSelect(action.id)}>
      {itemContent}
    </QDropdownMenuItem>
  );
}

function getGitActionIcon(actionId: GitMenuActionId) {
  switch (actionId) {
    case "commit":
      return <GitCommit size={12} weight="bold" />;
    case "push":
      return <CloudArrowUp size={12} weight="bold" />;
    case "sync":
      return <ArrowsClockwise size={12} weight="bold" />;
    case "publish":
      return <GitBranch size={12} weight="bold" />;
    case "create-pr":
      return <GitPullRequest size={12} weight="bold" />;
    case "view-pr":
      return <Eye size={12} weight="bold" />;
    case "branch-here":
      return <GitFork size={12} weight="bold" />;
    default:
      return <CloudArrowUp size={12} weight="bold" />;
  }
}
