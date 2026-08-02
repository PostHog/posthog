import {
  ArrowsClockwise,
  CloudArrowUp,
  Copy,
  Eye,
  GitBranch,
  GitCommit,
  GitFork,
  GitPullRequest,
  PushPin,
} from "@phosphor-icons/react";
import {
  getPrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
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
import type { SyntheticEvent } from "react";
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
 * list; when the task has several PRs (multi-repository tasks) the badge
 * carries a "+N" count and the menu lists every PR — click opens it on
 * GitHub, the pin swaps which one the badge shows. Cloud tasks without a PR
 * render nothing.
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
            prItems={buildPrMenuItems(
              { url: pr.url, state: pr.state, merged, draft },
              otherUrls,
              prSummaries,
              otherPrDetails,
            )}
            isPrPending={isPrActionPending}
            gitItems={gitItems}
            onGitSelect={gitActions.openAction}
            onPrSelect={executePrAction}
            onPinPr={setPrimaryPr}
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

interface PrMenuItem {
  url: string;
  label: string;
  summary: string | null;
  repoLabel: string | null;
  visual: ReturnType<typeof getPrVisualConfig> | null;
  isPrimary: boolean;
}

interface PrimaryPrDetails {
  url: string;
  state: string;
  merged: boolean;
  draft: boolean;
}

/**
 * Every PR the task has, primary first. Repo labels only appear when the PRs
 * span more than one repo (multi-repository tasks) — for single-repo tasks
 * the number alone is unambiguous.
 */
function buildPrMenuItems(
  primary: PrimaryPrDetails,
  otherUrls: string[],
  summaries: Record<string, string>,
  details: Record<string, PrStateDetails>,
): PrMenuItem[] {
  const urls = [primary.url, ...otherUrls];
  const parsedByUrl = new Map(urls.map((url) => [url, parseGithubUrl(url)]));
  const repoKeys = new Set(
    urls.map((url) => {
      const parsed = parsedByUrl.get(url);
      return parsed ? `${parsed.owner}/${parsed.repo}`.toLowerCase() : url;
    }),
  );
  const multiRepo = repoKeys.size > 1;
  return urls.map((url) => {
    const parsed = parsedByUrl.get(url);
    const isPrimary = url === primary.url;
    const detail = isPrimary ? primary : details[url];
    return {
      url,
      label: parsed?.kind === "pr" ? `#${parsed.number}` : url,
      summary: summaries[url] ?? null,
      repoLabel: multiRepo && parsed ? `${parsed.owner}/${parsed.repo}` : null,
      visual: detail
        ? getPrVisualConfig(detail.state, detail.merged, detail.draft)
        : null,
      isPrimary,
    };
  });
}

interface PrBadgeControlProps {
  prUrl: string;
  prState: string;
  merged: boolean;
  draft: boolean;
  branchName: string | null;
  prItems: PrMenuItem[];
  isPrPending: boolean;
  gitItems: GitMenuAction[];
  onGitSelect: (id: GitMenuActionId) => void;
  onPrSelect: (action: PrActionType) => void;
  onPinPr: (url: string) => void;
}

function PrBadgeControl({
  prUrl,
  prState,
  merged,
  draft,
  branchName,
  prItems,
  isPrPending,
  gitItems,
  onGitSelect,
  onPrSelect,
  onPinPr,
}: PrBadgeControlProps) {
  const config = getPrVisualConfig(prState, merged, draft);
  const lifecycleItems = config.actions;
  const hasMultiplePrs = prItems.length > 1;
  const mergedCount = prItems.filter(
    (item) => item.visual?.label === "Merged",
  ).length;
  const hasMenuItems = gitItems.length + lifecycleItems.length > 0;
  const hasDropdown = hasMenuItems || !!branchName || hasMultiplePrs;

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
        otherCount={prItems.length - 1}
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
          <DropdownMenu.Content size="1" align="end" className="max-w-[320px]">
            {hasMultiplePrs && (
              <>
                <DropdownMenu.Label>
                  Pull requests
                  {mergedCount > 0 &&
                    ` · ${mergedCount} of ${prItems.length} merged`}
                </DropdownMenu.Label>
                {prItems.map((item) => (
                  <PrMenuRow key={item.url} item={item} onPin={onPinPr} />
                ))}
              </>
            )}
            {hasMultiplePrs && gitItems.length > 0 && (
              <DropdownMenu.Separator />
            )}
            {gitItems.map((item) => (
              <GitDropdownItem
                key={item.id}
                action={item}
                onSelect={onGitSelect}
                renderAs="radix"
              />
            ))}
            {(gitItems.length > 0 || hasMultiplePrs) &&
              lifecycleItems.length > 0 && <DropdownMenu.Separator />}
            {/* With several PRs, scope the lifecycle actions to the badge's PR
                so "Close PR" can't read as closing all of them. */}
            {hasMultiplePrs && lifecycleItems.length > 0 && (
              <DropdownMenu.Label>
                {parsePrNumber(prUrl) ? `#${parsePrNumber(prUrl)}` : "This PR"}
              </DropdownMenu.Label>
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
            {branchName && (
              <>
                {(hasMenuItems || hasMultiplePrs) && <DropdownMenu.Separator />}
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

/**
 * One PR in the dropdown's pull-request list. The row is a link (click →
 * GitHub); the trailing pin swaps which PR the header badge shows. The
 * primary row wears a filled pin, others reveal theirs on hover.
 */
function PrMenuRow({
  item,
  onPin,
}: {
  item: PrMenuItem;
  onPin: (url: string) => void;
}) {
  // Swallow the full pointer sequence so pinning neither follows the link
  // nor lets the menu treat it as selecting the row.
  const interceptPointer = (e: SyntheticEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  return (
    <DropdownMenu.Item asChild>
      <a
        href={item.url}
        target="_blank"
        rel="noopener noreferrer"
        className="group h-auto py-1"
      >
        <Flex align="center" gap="2" className="min-w-0 flex-1">
          <PrStateIcon visual={item.visual} />
          <Flex direction="column" className="min-w-0 flex-1">
            <Flex align="center" gap="1" className="min-w-0">
              <Text size="1" weight="medium" className="shrink-0">
                {item.label}
              </Text>
              {item.visual && (
                <Text size="1" color={item.visual.color} className="shrink-0">
                  {item.visual.label}
                </Text>
              )}
              {item.repoLabel && (
                <Text size="1" color="gray" className="truncate">
                  {item.repoLabel}
                </Text>
              )}
            </Flex>
            {item.summary && (
              <Text size="1" color="gray" className="truncate">
                {item.summary}
              </Text>
            )}
          </Flex>
          {item.isPrimary ? (
            <PushPin
              size={12}
              weight="fill"
              className="shrink-0 text-(--gray-9)"
              aria-label="Shown in the task header"
            />
          ) : (
            <button
              type="button"
              title={`Show ${item.label} in the task header`}
              aria-label={`Show ${item.label} in the task header`}
              className="shrink-0 rounded p-0.5 text-(--gray-11) opacity-0 transition-opacity hover:bg-(--gray-a4) focus-visible:opacity-100 group-hover:opacity-100"
              onPointerDown={interceptPointer}
              onPointerUp={interceptPointer}
              onClick={(e) => {
                interceptPointer(e);
                onPin(item.url);
              }}
            >
              <PushPin size={12} />
            </button>
          )}
        </Flex>
      </a>
    </DropdownMenu.Item>
  );
}

function PrStateIcon({ visual }: { visual: PrMenuItem["visual"] }) {
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
