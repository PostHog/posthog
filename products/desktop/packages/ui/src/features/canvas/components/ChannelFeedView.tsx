import {
  AppWindowIcon,
  ArrowSquareOutIcon,
  ChatCircleIcon,
  GitBranchIcon,
  GitPullRequestIcon,
  PlusIcon,
  RobotIcon,
} from "@phosphor-icons/react";
import { taskFeedRunStatus } from "@posthog/core/canvas/channelFeed";
import {
  RUN_STATUS_LABELS,
  runStatusVariant,
} from "@posthog/core/canvas/runStatus";
import { buildThreadTimeline } from "@posthog/core/canvas/threadTimeline";
import type { PrCheck } from "@posthog/core/git/router-schemas";
import { parsePrNumber } from "@posthog/core/git-interaction/prStatus";
import { xmlToPlainText } from "@posthog/core/message-editor/content";
import { isTaskActivelyRunning } from "@posthog/core/sidebar/taskRunning";
import {
  AvatarGroup,
  Badge,
  Card,
  CardContent,
  cn,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Skeleton,
  Spinner,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import {
  formatRelativeTimeShort,
  mergePrUrls,
  readPrUrls,
} from "@posthog/shared";
import type {
  SignalReport,
  Task,
  TaskRunStatus,
  UserBasic,
} from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useArchiveTask } from "@posthog/ui/features/archive/useArchiveTask";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { TaskTabIcon } from "@posthog/ui/features/browser-tabs/TaskTabIcon";
import {
  type FeedEntry,
  type FeedKindFilter,
  feedEntryMatchesKind,
  mergeFeedEntries,
  stripContextBlocks,
} from "@posthog/ui/features/canvas/components/channelFeedDisplay";
import { ReportFeedRow } from "@posthog/ui/features/canvas/components/ReportFeedRow";
import { ReportFilterControls } from "@posthog/ui/features/canvas/components/ReportFilterControls";
import {
  TaskRowContextMenu,
  TaskRowDropdownMenu,
  type TaskRowMenuProps,
} from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { buildRows } from "@posthog/ui/features/canvas/components/taskArtifactRows";
import type { ChannelFeedSystemMessage } from "@posthog/ui/features/canvas/hooks/useChannelFeedMessages";
import type { ChannelReportsFilters } from "@posthog/ui/features/canvas/hooks/useChannelReports";
import { useChannelTaskData } from "@posthog/ui/features/canvas/hooks/useChannelTaskData";
import { useMarkTaskActivityRead } from "@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead";
import { useTaskThread } from "@posthog/ui/features/canvas/hooks/useTaskThread";
import type { ThreadPanelTab } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { taskCardNavigation } from "@posthog/ui/features/canvas/taskCardNavigation";
import { canvasArtifactOpenHandler } from "@posthog/ui/features/canvas/utils/canvasArtifactNavigation";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { useCommandCenterStore } from "@posthog/ui/features/command-center/commandCenterStore";
import { placeTaskInCommandCenter } from "@posthog/ui/features/command-center/placeTaskInCommandCenter";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { usePrArtifact } from "@posthog/ui/features/git-interaction/usePrArtifact";
import { usePrTitles } from "@posthog/ui/features/git-interaction/usePrDetails";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { usePrChecks } from "@posthog/ui/features/pr-review/usePrChecks";
import { StopCloudRunDialog } from "@posthog/ui/features/sessions/components/StopCloudRunDialog";
import { ArchiveRunningTaskDialog } from "@posthog/ui/features/sidebar/components/ArchiveRunningTaskDialog";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import {
  type SidebarPrState,
  useTaskPrStatus,
} from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useRenameTask } from "@posthog/ui/features/tasks/useTaskMutations";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { useInView } from "@posthog/ui/primitives/hooks/useInView";
import { toast } from "@posthog/ui/primitives/toast";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { parseHttpsUrl } from "@posthog/ui/utils/posthogLinks";
import { Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import {
  memo,
  type ReactElement,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

// Feed rows poll their reply counts slower than the open thread panel — the
// shared query key means an open panel naturally speeds the row up too.
const FEED_REPLIES_POLL_INTERVAL_MS = 15_000;

// Once a PR exists its GitHub state is the truest top-line status — more
// accurate than the run status, which routinely lingers on "in_progress"
// (or a stale cloud status) after the agent opens the PR. Mirrors the PR
// states the sidebar's TaskIcon already renders.
const PR_STATE_LABELS: Record<
  Exclude<SidebarPrState, null>,
  { label: string; variant: "success" | "info" | "default" | "destructive" }
> = {
  merged: { label: "Merged", variant: "default" },
  open: { label: "PR ready", variant: "info" },
  draft: { label: "Draft PR", variant: "default" },
  closed: { label: "Closed", variant: "destructive" },
};

function statusBadge(status: TaskRunStatus) {
  return (
    <Badge variant={runStatusVariant(status)}>
      {status === "in_progress" && <Spinner className="size-2.5" />}
      {RUN_STATUS_LABELS[status]}
    </Badge>
  );
}

interface TaskStatusDisplay {
  // The run/environment badge ("Local", "Completed", "In progress", …).
  base: ReactNode;
  // The PR's GitHub state, shown alongside the run badge when a PR exists.
  prState: Exclude<SidebarPrState, null> | null;
  isMerged: boolean;
}

// Live status for the card, derived the same way the sidebar's TaskIcon does
// (via useChannelTaskData: local session + workspace + cloud run). The raw
// `latest_run.status` alone is wrong for local runs — the backend row often
// stays "queued" while the agent runs on the creator's machine — so it is
// only trusted for cloud runs and terminal states (which imply a sync).
//
// Once a PR exists its state ("PR ready", "Merged", …) is the sole top-line
// status — it replaces the run badge rather than sitting next to it, so a
// shipped task never reads "Ready + Merged" or a stale "In progress + PR
// ready". A failed/cancelled run suppresses the PR badge instead — that is a
// deliberate end state we should not soften with a PR.
function useTaskStatusDisplay(task: Task): TaskStatusDisplay {
  const data = useChannelTaskData(task);
  const { prState } = useTaskPrStatus({
    id: task.id,
    cloudPrUrl: data?.cloudPrUrl ?? null,
    taskRunEnvironment: data?.taskRunEnvironment ?? null,
  });
  const status = data?.taskRunStatus ?? task.latest_run?.status;
  const environment = data?.taskRunEnvironment ?? task.latest_run?.environment;
  const displayStatus = taskFeedRunStatus({ status, environment });
  // `prState` is resolved async from git/`gh` and is routinely null for cloud
  // tasks (the details fetch hasn't landed, or there's no cached row). But the
  // PR URL itself is a hard signal a PR exists — the card's "PR" link keys off
  // exactly this. Fall back to it so the badge and the link never disagree; a
  // known URL with no resolved state is shown as the neutral "open" ("PR
  // ready"), never something stronger like "merged".
  const hasPrUrl =
    typeof (data?.cloudPrUrl ?? task.latest_run?.output?.pr_url) === "string";
  const effectivePrState: Exclude<SidebarPrState, null> | null =
    prState ?? (hasPrUrl ? "open" : null);
  const showPrState =
    !!effectivePrState && status !== "failed" && status !== "cancelled";

  let base: ReactNode;
  if (data?.needsPermission) {
    // Live, actionable states still win over the PR badge — the agent is
    // waiting on the user right now, which matters more than a PR existing.
    base = <Badge variant="warning">Needs input</Badge>;
  } else if (data?.isGenerating) {
    base = (
      <Badge variant="info">
        <Spinner className="size-2.5" />
        In progress
      </Badge>
    );
  } else if (showPrState) {
    // Otherwise the PR badge is the whole story once a PR exists; skip the run
    // badge so we never show "Ready + Merged" or a stale "In progress".
    base = null;
  } else if (!status) {
    base = <Badge>Draft</Badge>;
  } else if (displayStatus) {
    base = statusBadge(displayStatus);
  } else {
    // Local, non-terminal: the run status is unreliable (the backend row stays
    // "queued" while the agent runs on the creator's machine), so we render no
    // status badge rather than a misleading one.
    base = null;
  }

  return {
    base,
    prState: showPrState ? effectivePrState : null,
    isMerged: showPrState && effectivePrState === "merged",
  };
}

// The merged badge borrows the purple GitHub-merge accent (matching the
// sidebar's TaskIcon merge glyph). Quill has no purple variant, so we tint a
// neutral badge with the Radix purple scale — allowed inline because the
// values are CSS variables, not hardcoded colors.
function PrStateBadge({ prState }: { prState: Exclude<SidebarPrState, null> }) {
  const { label, variant } = PR_STATE_LABELS[prState];
  if (prState === "merged") {
    return (
      <Badge
        variant="default"
        style={{
          backgroundColor: "var(--purple-a3)",
          color: "var(--purple-11)",
        }}
      >
        {label}
      </Badge>
    );
  }
  return <Badge variant={variant}>{label}</Badge>;
}

function TaskStatusBadge({ display }: { display: TaskStatusDisplay }) {
  return (
    <div className="flex shrink-0 items-center gap-1">
      {display.base}
      {display.prState && <PrStateBadge prState={display.prState} />}
    </div>
  );
}

// The one-line task summary pinned under the activity panel's tabs: icon,
// truncated title, live status. Links to the task's full view.
export function TaskSummaryRow({
  task,
  channelId,
}: {
  task: Task;
  channelId: string;
}) {
  const statusDisplay = useTaskStatusDisplay(task);
  return (
    <Link
      {...taskCardNavigation(channelId, task.id)}
      preload="intent"
      className="flex min-w-0 items-center gap-2 border-b px-3 py-2 text-inherit no-underline outline-none transition-colors hover:bg-fill-hover focus-visible:ring-(--accent-8) focus-visible:ring-2"
    >
      <TaskTabIcon task={task} size={14} />
      <span className="min-w-0 flex-1 truncate font-medium text-[13px]">
        {task.title || "Untitled task"}
      </span>
      <TaskStatusBadge display={statusDisplay} />
    </Link>
  );
}

// A kickoff a user just submitted, before its task exists on the backend. The
// feed shows it optimistically so a submit reacts instantly instead of waiting
// on the create round trip; it's swapped for the real card once created.
export interface PendingKickoff {
  id: string;
  prompt: string;
}

// A stable empty default so the `pending` prop doesn't hand memoized children a
// fresh array every render.
const NO_PENDING: PendingKickoff[] = [];

// The task the message kicked off, as a card everyone in the channel sees:
// bold title + status up top, then run metadata.
export function TaskCard({
  task,
  channelId,
  inThread = false,
  onOpen,
}: {
  task: Task;
  channelId: string;
  inThread?: boolean;
  onOpen?: () => void;
}) {
  const statusDisplay = useTaskStatusDisplay(task);
  const prUrl =
    typeof task.latest_run?.output?.pr_url === "string"
      ? task.latest_run.output.pr_url
      : undefined;
  const stage = task.latest_run?.stage;
  return (
    <Link
      {...taskCardNavigation(channelId, task.id)}
      preload="intent"
      onClick={onOpen}
      className={cn(
        "mt-1.5 block w-full text-inherit no-underline outline-none focus-visible:ring-(--accent-8) focus-visible:ring-2",
        inThread ? "rounded-none" : "rounded-sm",
      )}
    >
      <Card
        size="sm"
        className={cn(
          "w-full cursor-pointer py-0 transition-none hover:bg-fill-hover",
          statusDisplay.isMerged
            ? "border-transparent bg-(--purple-a2) shadow-[0_0_0_1px_var(--purple-8)] hover:bg-(--purple-a3) dark:bg-(--purple-a1) dark:hover:bg-(--purple-a2)"
            : "hover:border-border-primary",
          inThread ? "rounded-none" : "rounded-sm",
        )}
      >
        <CardContent className="flex flex-col gap-1 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <TaskTabIcon task={task} size={14} />
              <span className="line-clamp-2 font-medium text-sm">
                {task.title || "Untitled task"}
              </span>
            </div>
            <TaskStatusBadge display={statusDisplay} />
          </div>
          {(stage || task.repository || prUrl) && (
            <div className="flex min-w-0 items-center gap-3">
              {task.repository && (
                <span className="inline-flex items-center gap-1 text-muted-foreground text-xs">
                  <GitBranchIcon size={12} />
                  {task.repository}
                </span>
              )}
              {stage && (
                <Text size="1" className="truncate text-muted-foreground">
                  {stage}
                </Text>
              )}
              {prUrl && (
                <span className="inline-flex shrink-0 items-center gap-1 text-muted-foreground text-xs">
                  <ArrowSquareOutIcon size={12} />
                  PR
                </span>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </Link>
  );
}

function channelTaskStarter(task: Task): UserBasic | null {
  return task.origin_product === "user_created"
    ? (task.created_by ?? null)
    : null;
}

export function ExpandablePrompt({
  children,
  lines,
  expandedContent,
}: {
  children: string;
  lines: 2 | 4;
  /** Rendered in place of the raw text when expanded — lets the collapsed
   * clamp stay plain text (the cut is measured on text) while the expanded
   * view renders rich markdown. */
  expandedContent?: ReactNode;
}) {
  // The prompt is truncated by hand — not with -webkit-line-clamp — so the
  // "more" toggle can sit inline right after the ellipsis on the last visible
  // line, like "...prompt…more". A hidden copy of the full text is measured to
  // find how much fits, leaving room for the toggle; the visible body renders
  // the cut. Measuring the full text (not the visible, already-cut text) keeps
  // the ResizeObserver stable instead of oscillating as content swaps.
  const [measure, setMeasure] = useState<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [cut, setCut] = useState<string | null>(null);

  const measureRef = useCallback((node: HTMLDivElement | null) => {
    setMeasure(node);
  }, []);

  useEffect(() => {
    if (!measure || expanded) return;

    const compute = () => {
      const lineHeight = parseFloat(getComputedStyle(measure).lineHeight);
      const maxHeight = lineHeight * lines;
      if (measure.scrollHeight <= maxHeight + 0.5) {
        setCut(null);
        return;
      }
      // Find the longest prefix that still fits in `lines` once "…more" is
      // appended — so the toggle can sit inline right after the ellipsis on the
      // last line. We probe by swapping the measure's text node to "prefix…more"
      // and reading scrollHeight (no per-line geometry), then restore it so the
      // next resize re-measures against the uncut prompt. `children` is the
      // source of truth (and a dep below) so a polled prompt update re-measures
      // even when its rendered size is unchanged.
      const text = measure.lastChild;
      if (text?.nodeType !== Node.TEXT_NODE) {
        setCut(null);
        return;
      }
      const fits = (end: number) => {
        text.nodeValue = `${children.slice(0, end).trimEnd()}…more`;
        return measure.scrollHeight <= maxHeight + 0.5;
      };
      let lo = 0;
      let hi = children.length;
      let best = 0;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (fits(mid)) {
          best = mid;
          lo = mid + 1;
        } else {
          hi = mid - 1;
        }
      }
      text.nodeValue = children;
      // Even when no full character fits alongside "…more" (best === 0, only at
      // extreme narrow widths), still cut so the toggle shows and the prompt
      // stays expandable instead of silently clipped.
      setCut(`${children.slice(0, best).trimEnd()}…`);
    };

    compute();
    const observer = new ResizeObserver(compute);
    observer.observe(measure);
    return () => observer.disconnect();
  }, [children, expanded, lines, measure]);

  const truncated = cut !== null;
  const displayText = expanded || !truncated ? children : cut;

  const clampClass = lines === 2 ? "max-h-[2lh]" : "max-h-[4lh]";

  if (expanded && expandedContent !== undefined) {
    return (
      <div data-slot="expandable-prompt" className="min-w-0">
        {expandedContent}
        <button
          type="button"
          aria-expanded
          className="text-muted-foreground text-xs underline underline-offset-2 hover:text-foreground"
          onClick={(event) => {
            event.stopPropagation();
            setExpanded(false);
          }}
        >
          less
        </button>
      </div>
    );
  }

  return (
    // A plain div, deliberately not ThreadItemBody: quill's thread body pins
    // font-size to text-sm and color to --foreground, which would flatten the
    // card's title/prompt hierarchy. Typography comes from the caller.
    <div
      data-slot="expandable-prompt"
      className="wrap-break-word relative min-w-0 overflow-hidden whitespace-pre-line"
    >
      <div
        aria-hidden
        className="pointer-events-none invisible absolute top-0 right-0 left-0"
      >
        <div ref={measureRef} className="wrap-break-word whitespace-pre-line">
          {children}
        </div>
      </div>
      <div
        className={cn(!expanded && clampClass, !expanded && "overflow-hidden")}
      >
        {displayText}
        {truncated && (
          <button
            type="button"
            aria-expanded={expanded}
            className="pl-1 text-muted-foreground text-xs underline underline-offset-2 hover:text-foreground"
            onClick={(event) => {
              event.stopPropagation();
              setExpanded((value) => !value);
            }}
          >
            {expanded ? "less" : "more"}
          </button>
        )}
      </div>
    </div>
  );
}

const CHIP_CLASS =
  "inline-flex h-6 items-center gap-1.5 rounded-md border border-(--gray-6) bg-(--gray-4) px-2 font-medium text-(--gray-11) text-xs transition-colors hover:border-(--gray-7) hover:bg-(--gray-5)";

// A popover that opens on hover (with a short close delay so the pointer can
// travel into it) and on click for keyboard and touch. Quill has no HoverCard,
// so this composes one from Popover; content mounts only while open, which
// keeps per-item data fetches (PR checks, titles) off the feed's steady-state
// render. Deliberately no focus handlers: closing returns focus to the
// trigger, so opening on focus re-opens the popover in an endless blink loop
// (and hands it to whichever trigger focus lands on next).
function HoverPopover({
  trigger,
  content,
  contentClassName,
}: {
  trigger: ReactElement;
  content: ReactNode;
  contentClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  useEffect(() => () => clearTimeout(closeTimer.current), []);
  const show = useCallback(() => {
    clearTimeout(closeTimer.current);
    setOpen(true);
  }, []);
  const hide = useCallback(() => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), 150);
  }, []);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={trigger}
        onMouseEnter={show}
        onMouseLeave={hide}
      />
      <PopoverContent
        // Quill's popover is a fixed 18rem; these cards size to their content.
        className={cn("w-auto gap-0 p-2", contentClassName)}
        onMouseEnter={show}
        onMouseLeave={hide}
        onClick={(event) => event.stopPropagation()}
      >
        {content}
      </PopoverContent>
    </Popover>
  );
}

// One line summarizing a PR's CI: failing beats running beats passing.
function summarizePrChecks(
  checks: PrCheck[] | null | undefined,
): { label: string; color: string } | null {
  if (!checks || checks.length === 0) return null;
  let failed = 0;
  let pending = 0;
  let passed = 0;
  for (const check of checks) {
    if (check.bucket === "fail" || check.bucket === "cancel") failed++;
    else if (check.bucket === "pending") pending++;
    else if (check.bucket === "pass") passed++;
  }
  if (failed) {
    return {
      label: `CI failing · ${failed} ${failed === 1 ? "check" : "checks"}`,
      color: "var(--red-11)",
    };
  }
  if (pending) return { label: "CI running", color: "var(--amber-11)" };
  if (passed) return { label: "CI passing", color: "var(--green-11)" };
  return null;
}

function PrCiLine({ url }: { url: string }) {
  const checks = usePrChecks(url);
  const ci = summarizePrChecks(checks.data);
  if (!ci) {
    if (!checks.isPending) return null;
    return (
      <div className="flex items-center gap-1.5 text-(--gray-9) text-xs">
        <Spinner className="size-3" />
        Checking CI…
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 text-(--gray-11) text-xs">
      <span
        className="size-1.5 rounded-full"
        style={{ backgroundColor: ci.color }}
      />
      {ci.label}
    </div>
  );
}

// The hover card for one PR chip: number + state, truncated title, CI line.
// Mounted only while the popover is open, so its title/checks fetches never
// run for chips just sitting in the feed.
function PrPopoverContent({ url }: { url: string }) {
  const { prNumber, stateLabel, Icon, iconColor } = usePrArtifact(url);
  const prUrls = useMemo(() => [url], [url]);
  const titles = usePrTitles(prUrls);
  return (
    <div className="flex max-w-72 flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-xs">
        <Icon size={13} style={{ color: iconColor }} />
        <span className="font-semibold">
          {prNumber ? `#${prNumber}` : "PR"}
        </span>
        {stateLabel && <span className="text-(--gray-9)">{stateLabel}</span>}
      </div>
      {titles[url] ? (
        <div className="truncate font-medium text-sm">{titles[url]}</div>
      ) : (
        // The title resolves via gh after open; hold its line so the card
        // doesn't jump when it lands.
        <div className="flex h-5 items-center">
          <Spinner className="size-3" />
        </div>
      )}
      <PrCiLine url={url} />
    </div>
  );
}

// One PR inside the "+N PRs" popover: state icon, number, truncated title,
// CI dot. Same mounted-only-while-open economics as PrPopoverContent.
function PrPopoverRow({ url }: { url: string }) {
  const { safeUrl, prNumber, Icon, iconColor } = usePrArtifact(url);
  const prUrls = useMemo(() => [url], [url]);
  const titles = usePrTitles(prUrls);
  const checks = usePrChecks(safeUrl);
  const ci = summarizePrChecks(checks.data);
  if (!safeUrl) return null;
  return (
    <button
      type="button"
      className="flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-(--gray-4)"
      onClick={(event) => {
        event.stopPropagation();
        openExternalUrl(safeUrl);
      }}
    >
      <Icon size={13} className="shrink-0" style={{ color: iconColor }} />
      <span className="shrink-0 font-medium">
        {prNumber ? `#${prNumber}` : "PR"}
      </span>
      <span className="min-w-0 flex-1 truncate text-(--gray-11)">
        {titles[url] ?? ""}
      </span>
      {ci ? (
        <span
          title={ci.label}
          className="size-1.5 shrink-0 rounded-full"
          style={{ backgroundColor: ci.color }}
        />
      ) : (
        checks.isPending && <Spinner className="size-3 shrink-0" />
      )}
    </button>
  );
}

// The closed chip renders from the URL alone — no data fetch. usePrArtifact
// starts a per-PR GitHub details query (a `gh` subprocess per distinct PR),
// and the feed mounts every card, so the state/title/CI lookups stay inside
// the hover card, which mounts only when opened.
function PrChip({ url }: { url: string }) {
  const parsed = parseHttpsUrl(url);
  const safeUrl = parsed?.origin === "https://github.com" ? parsed.href : null;
  if (!safeUrl) return null;
  const prNumber = parsePrNumber(safeUrl);
  return (
    <HoverPopover
      trigger={
        <button
          type="button"
          className={CHIP_CLASS}
          title="Pull request"
          onClick={(event) => {
            event.stopPropagation();
            openExternalUrl(safeUrl);
          }}
        >
          <GitPullRequestIcon size={12} />
          {prNumber ? `#${prNumber}` : "PR"}
        </button>
      }
      content={<PrPopoverContent url={safeUrl} />}
    />
  );
}

function OverflowChip({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <HoverPopover
      trigger={
        <button
          type="button"
          className={cn(CHIP_CLASS, "border-dashed text-(--gray-9)")}
          onClick={(event) => event.stopPropagation()}
        >
          {label}
        </button>
      }
      content={<div className="flex min-w-60 flex-col gap-0.5">{children}</div>}
    />
  );
}

const FeedItem = memo(function FeedItem({
  task,
  inView,
  showRepo,
  onOpenTask,
  onOpenThread,
}: {
  task: Task;
  inView: boolean;
  showRepo: boolean;
  onOpenTask: (task: Task) => void;
  onOpenThread: (task: Task, tab?: ThreadPanelTab) => void;
}) {
  const { mutate: markTasksRead } = useMarkTaskActivityRead();
  const statusDisplay = useTaskStatusDisplay(task);
  const taskData = useChannelTaskData(task);
  const { togglePin } = usePinnedTasks();
  const { archiveTask } = useArchiveTask();
  const { renameTask } = useRenameTask();
  const commandCenterCells = useCommandCenterStore((state) => state.cells);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleValue, setTitleValue] = useState(task.title);
  const [isSavingTitle, setIsSavingTitle] = useState(false);
  const [archiveConfirmOpen, setArchiveConfirmOpen] = useState(false);
  const [stopConfirmOpen, setStopConfirmOpen] = useState(false);
  const isActive = taskData ? isTaskActivelyRunning(taskData) : false;
  const canStop = taskData?.taskRunEnvironment === "cloud" && isActive;
  const starter = channelTaskStarter(task);
  const prompt = useMemo(
    () => stripContextBlocks(xmlToPlainText(task.description ?? "")),
    [task.description],
  );
  const prUrls = useMemo(
    () =>
      mergePrUrls(
        readPrUrls(task.latest_run?.output),
        taskData?.cloudPrUrl ? [taskData.cloudPrUrl] : [],
      ),
    [task.latest_run?.output, taskData?.cloudPrUrl],
  );
  const { messages } = useTaskThread(task.id, {
    pollIntervalMs: FEED_REPLIES_POLL_INTERVAL_MS,
    enabled: inView,
    markActivityRead: false,
  });
  // Canvas artifacts only exist as thread timeline announcements, so the rows
  // are built from the thread; file rows come from the run outputs either way.
  const artifacts = useMemo(
    () =>
      buildRows(task, buildThreadTimeline(messages), []).filter(
        (row) => row.kind === "canvas" || row.kind === "file",
      ),
    [task, messages],
  );
  // Only conversational human rows count as comments — agent/system rows
  // (turn_complete) would inflate the count and render authorless "U" bubbles
  // in the facepile, and human-authored event rows (comment announcements like
  // comment_state_changed) are activity, not something a person typed. Same
  // rule as buildThreadTimeline's human-message classification.
  const humanMessages = useMemo(
    () =>
      messages.filter(
        (m) => !m.event && (m.author_kind ?? "human") === "human",
      ),
    [messages],
  );
  // The starter leads the facepile — it's how the card attributes the task
  // (the prompt itself carries no name) — followed by comment participants.
  const authors = useMemo(() => {
    const seen = new Map<string, UserBasic>();
    if (starter) seen.set(starter.uuid, starter);
    for (const message of humanMessages) {
      const author = message.author;
      if (author && !seen.has(author.uuid)) seen.set(author.uuid, author);
    }
    return [...seen.values()].slice(0, 4);
  }, [humanMessages, starter]);
  const markRead = useCallback(() => {
    markTasksRead([
      { task_id: task.id, seen_before: new Date().toISOString() },
    ]);
  }, [markTasksRead, task.id]);
  const openTask = useCallback(() => {
    markRead();
    onOpenTask(task);
  }, [markRead, onOpenTask, task]);
  const beginTitleEdit = useCallback(() => {
    setTitleValue(task.title);
    setEditingTitle(true);
  }, [task.title]);
  const saveTitle = useCallback(() => {
    if (isSavingTitle) return;
    const newTitle = titleValue.trim();
    if (!newTitle || newTitle === task.title) {
      setEditingTitle(false);
      return;
    }
    setIsSavingTitle(true);
    void renameTask({
      taskId: task.id,
      currentTitle: task.title,
      newTitle,
    })
      .then(() => setEditingTitle(false))
      .catch(() => {
        toast.error("Couldn't rename task", { description: "Try again." });
      })
      .finally(() => setIsSavingTitle(false));
  }, [isSavingTitle, renameTask, task.id, task.title, titleValue]);
  const runArchive = useCallback(async () => {
    try {
      await archiveTask({ taskId: task.id });
    } catch (error) {
      toast.error("Couldn't archive task", { description: "Try again." });
      throw error;
    }
  }, [archiveTask, task.id]);
  const archiveTaskFromFeed = useCallback(() => {
    if (isActive) {
      setArchiveConfirmOpen(true);
      return;
    }
    void runArchive().catch(() => undefined);
  }, [isActive, runArchive]);
  const confirmArchive = useCallback(async () => {
    await runArchive();
    setArchiveConfirmOpen(false);
  }, [runArchive]);
  const menu: TaskRowMenuProps = useMemo(
    () => ({
      kind: "task",
      id: task.id,
      title: task.title,
      isPinned: taskData?.isPinned ?? false,
      task,
      channelId: task.channel ?? undefined,
      onAddToCommandCenter: commandCenterCells.includes(task.id)
        ? undefined
        : () => placeTaskInCommandCenter(task.id, task.title),
      onRename: beginTitleEdit,
      onStop: canStop ? () => setStopConfirmOpen(true) : undefined,
      onTogglePin: () => {
        void togglePin(task.id).catch(() => {
          toast.error("Couldn't update pin", { description: "Try again." });
        });
      },
      onArchive: archiveTaskFromFeed,
    }),
    [
      archiveTaskFromFeed,
      beginTitleEdit,
      canStop,
      task,
      commandCenterCells,
      task.channel,
      task.id,
      task.title,
      taskData?.isPinned,
      togglePin,
    ],
  );
  // A chip opens its artifact directly: canvases navigate to the canvas, files
  // open as a tab in the task view (the tab is staged in the layout store, then
  // the task view is opened to show it). Anything unopenable falls back to the
  // side pane's Artifacts tab.
  const openArtifact = useCallback(
    (artifact: (typeof artifacts)[number]) => {
      if (artifact.kind === "canvas") {
        const open = canvasArtifactOpenHandler(artifact.url);
        if (open) {
          open();
          return;
        }
      } else if (artifact.artifactId && artifact.runId) {
        // A task never opened in this session has no panel layout yet, and
        // openArtifactTab no-ops without one — seed it first so the staged tab
        // survives into the task view's mount (PanelLayout only initializes
        // when the layout is missing).
        const layoutStore = usePanelLayoutStore.getState();
        if (!layoutStore.getLayout(task.id))
          layoutStore.initializeTask(task.id);
        layoutStore.openArtifactTab(task.id, {
          runId: artifact.runId,
          artifactId: artifact.artifactId,
          name: artifact.name,
        });
        openTask();
        return;
      }
      onOpenThread(task, "artifacts");
    },
    [onOpenThread, openTask, task],
  );

  const visiblePrCount = prUrls.length >= 5 ? 1 : 2;
  return (
    <TaskRowContextMenu menu={menu}>
      <Card
        size="sm"
        role="button"
        tabIndex={0}
        className="mx-auto my-1.5 w-full max-w-[660px] cursor-pointer rounded-xl bg-(--gray-2) py-0 transition-colors hover:border-(--gray-7) hover:bg-(--gray-3)"
        onClick={(event) => {
          if (
            event.target instanceof Element &&
            event.target.closest('[data-slot="dropdown-menu-trigger"]')
          ) {
            return;
          }
          markRead();
          onOpenThread(task);
        }}
        onKeyDown={(event) => {
          // Only when the card itself has focus: descendant buttons (title, PR
          // and comment chips, the prompt toggle) bubble their key events here,
          // and preventDefault would swallow their own Enter/Space activation.
          if (event.target !== event.currentTarget) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            markRead();
            onOpenThread(task);
          }
        }}
      >
        <CardContent className="flex flex-col px-4 pt-3.5 pb-3">
          <div className="flex items-center gap-3">
            <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
              {editingTitle ? (
                <Input
                  autoFocus
                  aria-label="Task title"
                  value={titleValue}
                  disabled={isSavingTitle}
                  className="h-6 min-w-0 font-semibold text-sm"
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) => setTitleValue(event.target.value)}
                  onBlur={saveTitle}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      saveTitle();
                    } else if (event.key === "Escape") {
                      event.preventDefault();
                      setEditingTitle(false);
                    }
                  }}
                />
              ) : (
                <button
                  type="button"
                  className="min-w-0 truncate text-left font-semibold text-sm leading-snug"
                  onClick={(event) => {
                    event.stopPropagation();
                    openTask();
                  }}
                >
                  {task.title || "Untitled task"}
                </button>
              )}
              <span className="shrink-0 text-(--gray-9) text-xs">
                · {formatRelativeTimeShort(task.updated_at)}
              </span>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <TaskStatusBadge display={statusDisplay} />
              <TaskRowDropdownMenu menu={menu} />
            </div>
          </div>
          <div className="mt-1.5 text-(--gray-9) text-xs leading-normal">
            <ExpandablePrompt
              lines={2}
              expandedContent={
                <div className="whitespace-normal text-(--gray-11) [&_pre]:my-1.5">
                  <MarkdownRenderer content={prompt} />
                </div>
              }
            >
              {prompt || "A new task was started"}
            </ExpandablePrompt>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {showRepo && task.repository && (
              <span
                className={cn(CHIP_CLASS, "border-transparent bg-transparent")}
              >
                <GitBranchIcon size={12} />
                {task.repository}
              </span>
            )}
            {prUrls.slice(0, visiblePrCount).map((url) => (
              <PrChip key={url} url={url} />
            ))}
            {prUrls.length > visiblePrCount && (
              <OverflowChip
                label={`+${prUrls.length - visiblePrCount} ${
                  prUrls.length - visiblePrCount === 1 ? "PR" : "PRs"
                }`}
              >
                {prUrls.slice(visiblePrCount).map((url) => (
                  <PrPopoverRow key={url} url={url} />
                ))}
              </OverflowChip>
            )}
            {artifacts.slice(0, 2).map((artifact) => (
              <button
                key={artifact.key}
                type="button"
                className={CHIP_CLASS}
                onClick={(event) => {
                  event.stopPropagation();
                  openArtifact(artifact);
                }}
              >
                {artifact.kind === "canvas" ? (
                  <AppWindowIcon size={12} />
                ) : (
                  <FileIcon filename={artifact.name} size={12} />
                )}
                <span className="max-w-40 truncate">{artifact.name}</span>
              </button>
            ))}
            {artifacts.length > 2 && (
              <OverflowChip
                label={`+${artifacts.length - 2} ${
                  artifacts.length - 2 === 1 ? "file" : "files"
                }`}
              >
                {artifacts.slice(2).map((artifact) => (
                  <button
                    key={artifact.key}
                    type="button"
                    className={cn(CHIP_CLASS, "w-full")}
                    onClick={(event) => {
                      event.stopPropagation();
                      openArtifact(artifact);
                    }}
                  >
                    {artifact.kind === "canvas" ? (
                      <AppWindowIcon size={12} />
                    ) : (
                      <FileIcon filename={artifact.name} size={12} />
                    )}
                    <span className="truncate">{artifact.name}</span>
                  </button>
                ))}
              </OverflowChip>
            )}
            {humanMessages.length > 0 ? (
              <button
                type="button"
                className={CHIP_CLASS}
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenThread(task, "comments");
                }}
              >
                <ChatCircleIcon size={12} />
                <span className="font-semibold text-(--gray-9)">
                  {humanMessages.length}
                </span>
              </button>
            ) : (
              <button
                type="button"
                className={CHIP_CLASS}
                onClick={(event) => {
                  event.stopPropagation();
                  onOpenThread(task, "comments");
                }}
              >
                <PlusIcon size={12} />
                Comment
              </button>
            )}
            <span className="flex-1" />
            {authors.length > 0 && (
              <HoverPopover
                trigger={
                  // A real button: the popover trigger expects native button
                  // semantics, and it gives keyboard users a way to open the
                  // participant list.
                  <button
                    type="button"
                    aria-label="Participants"
                    className="inline-flex cursor-default"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {/* reverse: the stack sits at the card's right edge, so the
                      hover expansion must spread left, into the card — the
                      default spreads right, off the edge and clipped. */}
                    <AvatarGroup size="xs" stacked reverse>
                      {authors.map((author) => (
                        <UserAvatar key={author.uuid} user={author} size="xs" />
                      ))}
                    </AvatarGroup>
                  </button>
                }
                content={
                  <div className="flex flex-col gap-1.5">
                    {authors.map((author) => (
                      <div
                        key={author.uuid}
                        className="flex items-center gap-2 text-xs"
                      >
                        <UserAvatar user={author} size="xs" />
                        {userDisplayName(author)}
                      </div>
                    ))}
                  </div>
                }
              />
            )}
          </div>
        </CardContent>
      </Card>
      <ArchiveRunningTaskDialog
        open={archiveConfirmOpen}
        taskTitle={task.title}
        stopsCloudSandbox={taskData?.taskRunEnvironment === "cloud"}
        onConfirm={confirmArchive}
        onCancel={() => setArchiveConfirmOpen(false)}
      />
      <StopCloudRunDialog
        open={stopConfirmOpen}
        taskId={task.id}
        runId={task.latest_run?.id}
        title={`Stop "${task.title}"?`}
        buttonLabel="Stop task"
        onOpenChange={setStopConfirmOpen}
        onStopped={() => toast.success("Stop requested")}
      />
    </TaskRowContextMenu>
  );
});

// One feed row: owns the `content-visibility` boundary (so its box is always
// laid out and safe to observe) and reports whether it is near the viewport,
// letting `FeedItem` shed off-screen polling. The intrinsic-size estimate
// keeps the scrollbar stable while off-screen rows are skipped; `auto` still
// remembers each row's real height after first paint.
function FeedRow({
  task,
  showRepo,
  onOpenTask,
  onOpenThread,
}: {
  task: Task;
  showRepo: boolean;
  onOpenTask: (task: Task) => void;
  onOpenThread: (task: Task, tab?: ThreadPanelTab) => void;
}) {
  const [ref, inView] = useInView<HTMLDivElement>({ rootMargin: "1200px 0px" });
  return (
    <div
      ref={ref}
      className="[contain-intrinsic-size:auto_9rem] [content-visibility:auto]"
    >
      <FeedItem
        task={task}
        inView={inView}
        showRepo={showRepo}
        onOpenTask={onOpenTask}
        onOpenThread={onOpenThread}
      />
    </div>
  );
}

// The optimistic kickoff row: the user's prompt as a "Starting…" card, shown
// at the top of the feed the moment they submit. Deliberately dumb — no
// per-task data hooks or polls (there's no task id to query yet); it's
// replaced by a real FeedRow as soon as the task is created.
function PendingFeedRow({ pending }: { pending: PendingKickoff }) {
  return (
    <Card
      size="sm"
      className="mx-auto my-1.5 w-full max-w-[660px] rounded-xl bg-(--gray-2) py-0"
    >
      <CardContent className="flex flex-col px-4 pt-3.5 pb-3">
        <div className="flex items-start gap-3">
          <span className="min-w-0 flex-1 font-semibold text-sm leading-snug">
            New task
          </span>
          <Badge variant="info">
            <Spinner className="size-2.5" />
            Starting…
          </Badge>
        </div>
        <div className="mt-1.5 text-(--gray-9) text-xs leading-normal">
          <ExpandablePrompt lines={2}>{pending.prompt}</ExpandablePrompt>
        </div>
      </CardContent>
    </Card>
  );
}

// A card-less feed row for a synthetic announcement. Rows with an `author`
// render as that user (initials avatar + name — e.g. "Adam L · joined mobile");
// the rest render as "PostHog / Agent" (context lifecycle updates). Same chrome
// as a task row, minus the task card and reply footer.
function SystemFeedRow({ message }: { message: ChannelFeedSystemMessage }) {
  return (
    <div className="mx-auto flex w-full min-w-0 max-w-[660px] items-center gap-2 px-1 py-1.5 text-(--gray-9) text-xs">
      {message.author ? (
        <UserAvatar user={message.author} size="xs" />
      ) : (
        <RobotIcon size={14} className="shrink-0" />
      )}
      <span className="min-w-0 truncate">
        {message.author ? (
          <>
            <span className="font-medium text-(--gray-11)">
              {userDisplayName(message.author)}
            </span>{" "}
            {message.text}
          </>
        ) : (
          message.text
        )}
      </span>
      <span className="shrink-0">
        · {formatRelativeTimeShort(message.createdAt)}
      </span>
    </div>
  );
}

const DAY_MS = 86_400_000;

// "Today" / "Yesterday" / "Aug 8" (with the year once it differs) for the
// feed's day separators.
function feedDayLabel(iso: string, now: Date): string {
  const date = new Date(iso);
  const startOfDay = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOfDay(now) - startOfDay(date)) / DAY_MS);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(date.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}),
  });
}

/**
 * The loading stand-in for one feed card: the card frame with the title,
 * prompt lines, and footer facepile as pulsing bars, so the page keeps the
 * feed's shape while the query runs instead of collapsing to a spinner.
 */
function FeedRowSkeleton({ wide }: { wide?: boolean }) {
  return (
    <Card
      size="sm"
      className="mx-auto my-1.5 w-full max-w-[660px] rounded-xl py-0"
    >
      <CardContent className="flex flex-col px-4 pt-3.5 pb-3">
        <div className="flex items-start gap-3">
          <Skeleton className={cn("h-4", wide ? "w-3/5" : "w-2/5")} />
          <Skeleton className="ml-auto h-5 w-16 shrink-0 rounded-full" />
        </div>
        <div className="mt-2 flex flex-col gap-1.5">
          <Skeleton className="h-3 w-full" />
          <Skeleton className={cn("h-3", wide ? "w-1/2" : "w-3/4")} />
        </div>
        <div className="mt-3 flex items-center gap-2">
          <Skeleton className="size-5 rounded-full" />
          <Skeleton className="h-3 w-24" />
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * The loading feed: a faded stack of card skeletons under a separator-shaped
 * bar. Each card fainter than the one above, so the stack reads as content
 * arriving rather than a wall of grey.
 */
function FeedSkeleton() {
  return (
    <div aria-hidden className="flex flex-col">
      <div className="mx-auto flex w-full max-w-[660px] items-center gap-3 pt-5 pb-2">
        <span className="h-px flex-1 bg-(--gray-5)" />
        <Skeleton className="h-3 w-12" />
        <span className="h-px flex-1 bg-(--gray-5)" />
      </div>
      <FeedRowSkeleton wide />
      <div className="opacity-70">
        <FeedRowSkeleton />
      </div>
      <div className="opacity-40">
        <FeedRowSkeleton wide />
      </div>
      <div className="opacity-15">
        <FeedRowSkeleton />
      </div>
    </div>
  );
}

function DaySeparator({ label }: { label: string }) {
  return (
    <div className="mx-auto flex w-full max-w-[660px] items-center gap-3 pt-5 pb-2 font-semibold text-(--gray-9) text-[11px] uppercase tracking-wider">
      <span className="h-px flex-1 bg-(--gray-5)" />
      {label}
      <span className="h-px flex-1 bg-(--gray-5)" />
    </div>
  );
}

const FEED_KIND_FILTERS: readonly {
  value: FeedKindFilter;
  label: string;
}[] = [
  { value: "all", label: "All" },
  { value: "sessions", label: "Sessions" },
  { value: "reports", label: "Reports" },
];

// The channel feed: every task kicked off in the channel, newest first in a
// plain top-down scroll (Twitter-style, not a bottom-anchored chat).
// Multiplayer — the list is team-visible and polls for teammates' cards and
// status flips. Synthetic "PostHog agent" system rows (context lifecycle) are
// interleaved by timestamp, and day separators group the cards.
export function ChannelFeedView({
  channelId,
  tasks,
  pending = NO_PENDING,
  systemMessages,
  reports,
  onOpenReport,
  showKindFilter = true,
  reportFilters,
  onReportFiltersChange,
  isLoading,
  emptyState,
  intro,
  composer,
  onOpenTask,
  onOpenThread,
}: {
  channelId: string;
  tasks: Task[];
  pending?: PendingKickoff[];
  systemMessages?: ChannelFeedSystemMessage[];
  /** Reports interleaved into the feed as compact cards. Providing this (even
   * empty) also shows the sessions/reports kind filter. */
  reports?: SignalReport[];
  onOpenReport?: (reportId: string) => void;
  /** Off for single-kind feeds (a `type:report` saved feed), where the
   * sessions/reports tabs would only offer empty views. */
  showKindFilter?: boolean;
  /** When provided with its setter, the Reports tab shows the same funnel
   * menu as the sidebar Reports list. The caller owns the state and filters
   * the `reports` prop with it. */
  reportFilters?: ChannelReportsFilters;
  onReportFiltersChange?: (filters: ChannelReportsFilters) => void;
  isLoading: boolean;
  emptyState?: React.ReactNode;
  /** Rendered pinned above the first entry — the Slack-style channel intro
   * (name, creation line, onboarding card). When set, the feed renders even
   * with no entries instead of falling back to `emptyState`. */
  intro?: ReactElement;
  /** The new-session composer, rendered at the top of the feed column
   * (Twitter-style) so it scrolls away with the content and shares the cards'
   * width. Rendered in every state, including loading and empty. */
  composer?: ReactNode;
  onOpenTask: (task: Task) => void;
  onOpenThread: (task: Task, tab?: ThreadPanelTab) => void;
}) {
  // Archiving is local-only host state the server task list doesn't know about,
  // so a just-archived card would otherwise reappear on the next poll. Drop
  // archived tasks here, the same way the sidebar tree does via useChannelItems.
  const archivedTaskIds = useArchivedTaskIds();
  const visibleTasks = useMemo(
    () => tasks.filter((task) => !archivedTaskIds.has(task.id)),
    [tasks, archivedTaskIds],
  );

  // Which entry kinds show. Reset per space so a filter chosen in one channel
  // doesn't silently empty another. Only rendered when reports are wired in.
  const [kindFilter, setKindFilter] = useState<{
    channelId: string;
    value: FeedKindFilter;
  }>({ channelId, value: "all" });
  const activeKindFilter =
    kindFilter.channelId === channelId ? kindFilter.value : "all";

  const entries = useMemo<FeedEntry[]>(
    () =>
      mergeFeedEntries(
        visibleTasks,
        systemMessages ?? [],
        reports ?? [],
      ).filter((entry) => feedEntryMatchesKind(entry, activeKindFilter)),
    [visibleTasks, systemMessages, reports, activeKindFilter],
  );

  // The channel's dominant repo: on a single-repo channel every card would
  // repeat the same chip, so the repo chip only renders on tasks that target a
  // different repo than most of the channel.
  const dominantRepo = useMemo(() => {
    const counts = new Map<string, number>();
    for (const task of visibleTasks) {
      if (!task.repository) continue;
      counts.set(task.repository, (counts.get(task.repository) ?? 0) + 1);
    }
    let best: string | null = null;
    let bestCount = 0;
    for (const [repo, count] of counts) {
      if (count > bestCount) {
        best = repo;
        bestCount = count;
      }
    }
    return best;
  }, [visibleTasks]);

  const viewportRef = useRef<HTMLDivElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: channelId is a trigger — switching channels or finishing the initial load swaps/completes the rows without a remount, so re-land at the latest cards
  useLayoutEffect(() => {
    if (isLoading) return;
    viewportRef.current?.scrollTo({ top: 0 });
  }, [channelId, isLoading]);

  // Follow the feed to the top when *this* user posts (their card lands at the
  // top), but not when a teammate's card arrives via polling — a new `pending`
  // kickoff is only ever added by the local composer, so it's the right signal.
  const latestPendingId = pending[pending.length - 1]?.id;
  const prevPendingRef = useRef(latestPendingId);
  useEffect(() => {
    if (latestPendingId && latestPendingId !== prevPendingRef.current) {
      viewportRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }
    prevPendingRef.current = latestPendingId;
  }, [latestPendingId]);

  const composerBlock = composer && (
    <div className="mx-auto mb-2 w-full max-w-[660px]">{composer}</div>
  );

  // One row: the kind tabs, and — on the Reports kind only — the same compact
  // funnel the sidebar uses. Reports deliberately get no extra filter chrome
  // beyond that, so the row reads the same weight whichever kind is active.
  const kindFilterBlock = reports !== undefined && showKindFilter && (
    <div className="mx-auto flex w-full max-w-[660px] items-center gap-1 pt-1">
      <Tabs
        value={activeKindFilter}
        onValueChange={(value: string) =>
          setKindFilter({ channelId, value: value as FeedKindFilter })
        }
        className="min-w-0 flex-1"
      >
        <TabsList
          variant="line"
          className="quill-tabs-fill h-auto gap-0.5 border-b-0"
        >
          {FEED_KIND_FILTERS.map(({ value, label }) => (
            <TabsTrigger
              key={value}
              value={value}
              className="rounded-sm px-1 py-0.5 text-[13px]"
            >
              {label}
              {value === "reports" &&
                activeKindFilter !== "reports" &&
                (reports?.length ?? 0) > 0 && (
                  <span
                    className="ml-1 size-1.5 shrink-0 rounded-full bg-(--amber-9)"
                    role="img"
                    aria-label="Has reports"
                  />
                )}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {activeKindFilter === "reports" &&
        reportFilters &&
        onReportFiltersChange && (
          <ReportFilterControls
            filters={reportFilters}
            onChange={onReportFiltersChange}
            compact
          />
        )}
    </div>
  );

  // With the intro pinned, an emptied kind renders nothing below the tabs —
  // say so, and point at the next action, instead of dead space.
  const kindEmptyNote =
    activeKindFilter === "sessions" ? (
      <p className="mx-auto w-full max-w-[660px] py-6 text-center text-(--gray-10) text-[13px]">
        No sessions yet. Start one from the composer above.
      </p>
    ) : activeKindFilter === "reports" ? (
      <p className="mx-auto w-full max-w-[660px] py-6 text-center text-(--gray-10) text-[13px]">
        No reports here yet. Open the filter to widen the list.
      </p>
    ) : null;

  if (isLoading && pending.length === 0) {
    // Everything already known renders now. The skeleton cards hold the
    // feed's shape while keeping the intro and composer available.
    // feed's shape where the results are about to land.
    return (
      <div className="min-h-0 flex-1 overflow-y-auto" aria-busy="true">
        <output className="sr-only">Loading tasks</output>
        <div className="mx-auto w-full px-4 pt-4 pb-10">
          {intro && <div className="mx-auto w-full max-w-[660px]">{intro}</div>}
          {composerBlock}
          <FeedSkeleton />
        </div>
      </div>
    );
  }

  if (entries.length === 0 && pending.length === 0 && !intro) {
    return (
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full px-4 pt-4 pb-10">
          {composerBlock}
          {/* The filter stays visible while it's what emptied the list, so the
              user can switch back out of an empty kind. A selected kind shows
              its own note; the channel welcome is only for a truly empty feed. */}
          {kindFilterBlock}
          {activeKindFilter === "all" ? emptyState : kindEmptyNote}
        </div>
      </div>
    );
  }

  const now = new Date();
  const rows: ReactNode[] = [];
  // Pending kickoffs land at the top, newest first, under a "Today" separator.
  let lastDayLabel: string | null = null;
  if (pending.length > 0) {
    lastDayLabel = "Today";
    rows.push(<DaySeparator key="separator-pending" label="Today" />);
    for (let i = pending.length - 1; i >= 0; i--) {
      const p = pending[i];
      rows.push(<PendingFeedRow key={p.id} pending={p} />);
    }
  }
  for (const entry of entries) {
    const label = feedDayLabel(entry.createdAt, now);
    if (label !== lastDayLabel) {
      lastDayLabel = label;
      rows.push(<DaySeparator key={`separator-${label}`} label={label} />);
    }
    rows.push(
      entry.kind === "task" ? (
        <FeedRow
          key={entry.id}
          task={entry.task}
          showRepo={
            !!entry.task.repository && entry.task.repository !== dominantRepo
          }
          onOpenTask={onOpenTask}
          onOpenThread={onOpenThread}
        />
      ) : entry.kind === "report" ? (
        <ReportFeedRow
          key={entry.id}
          report={entry.report}
          onOpenReport={onOpenReport ?? (() => {})}
        />
      ) : (
        <SystemFeedRow key={entry.id} message={entry.message} />
      ),
    );
  }

  return (
    <div ref={viewportRef} className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full px-4 pt-4 pb-10">
        {intro && <div className="mx-auto w-full max-w-[660px]">{intro}</div>}
        {composerBlock}
        {kindFilterBlock}
        {rows.length === 0 ? kindEmptyNote : rows}
      </div>
    </div>
  );
}
