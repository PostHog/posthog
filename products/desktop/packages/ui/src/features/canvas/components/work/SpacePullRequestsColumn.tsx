import { GitPullRequestIcon } from "@phosphor-icons/react";
import {
  getPrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import { cn, MenuLabel } from "@posthog/quill";
import { formatRelativeTimeShort, readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  HoverPopover,
  PrPopoverContent,
} from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { getPrVisualIcon } from "@posthog/ui/features/git-interaction/prIcon";
import {
  type PrStateDetails,
  usePrDetailsMap,
  usePrTitles,
} from "@posthog/ui/features/git-interaction/usePrDetails";
import { usePrChecks } from "@posthog/ui/features/pr-review/usePrChecks";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { parseHttpsUrl } from "@posthog/ui/utils/posthogLinks";
import { useMemo } from "react";

/**
 * What the column reads in: what needs you, what is not ready, what landed —
 * and `pending`, for a PR whose state GitHub has not answered for yet. Pending
 * sits last and wears no heading, so a row settles upward into its group once
 * and never starts out under a heading that turns out to be wrong.
 */
type PrGroup = "open" | "draft" | "merged" | "closed" | "pending";

const GROUPS: readonly PrGroup[] = [
  "open",
  "draft",
  "merged",
  "closed",
  "pending",
];

const GROUP_LABEL: Record<PrGroup, string | null> = {
  open: "Open",
  draft: "Draft",
  merged: "Merged",
  closed: "Closed",
  pending: null,
};

interface PullRequestEntry {
  url: string;
  task: Task;
  group: PrGroup;
  details: PrStateDetails | undefined;
}

function groupOf(details: PrStateDetails | undefined): PrGroup {
  if (!details) return "pending";
  if (details.merged) return "merged";
  if (details.state === "closed") return "closed";
  return details.draft ? "draft" : "open";
}

const CI_DOT_CLASS = {
  pass: "bg-(--green-9)",
  fail: "bg-(--red-9)",
  pending: "bg-(--amber-9)",
} as const;

const CI_LABEL = {
  pass: "CI passing",
  fail: "CI failing",
  pending: "CI running",
} as const;

/** Failing beats running beats passing: the column answers "anything wrong?". */
function ciTone(
  checks: { bucket: string }[] | null | undefined,
): keyof typeof CI_DOT_CLASS | null {
  if (!checks || checks.length === 0) return null;
  if (checks.some((c) => c.bucket === "fail" || c.bucket === "cancel")) {
    return "fail";
  }
  if (checks.some((c) => c.bucket === "pending")) return "pending";
  return "pass";
}

/**
 * One pull request on one line: lifecycle glyph, number, title, CI, age. Its
 * state, CI detail and the session behind it live in the hover card the feed's
 * PR chips already open. Click opens GitHub.
 */
function PullRequestLine({
  entry,
  title,
  showChecks,
  muted = false,
}: {
  entry: PullRequestEntry;
  title: string | undefined;
  /** Only live PRs fetch checks: a merged one's CI is history. */
  showChecks: boolean;
  /** Its state has not come back yet, so the row waits rather than claims. */
  muted?: boolean;
}) {
  const checks = usePrChecks(showChecks ? entry.url : null);
  const tone = ciTone(checks.data);
  const config = getPrVisualConfig(
    entry.details?.state ?? "open",
    entry.details?.merged ?? false,
    entry.details?.draft ?? false,
  );
  const Icon = getPrVisualIcon(config.icon);
  const prNumber = parsePrNumber(entry.url);
  return (
    <HoverPopover
      trigger={
        <button
          type="button"
          className={cn(
            "flex h-7 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-[13px] transition-colors",
            "text-muted-foreground hover:bg-fill-hover hover:text-foreground",
          )}
          onClick={() => openExternalUrl(entry.url)}
        >
          <span className="flex size-3.5 shrink-0 items-center justify-center">
            <Icon
              size={13}
              style={muted ? undefined : { color: `var(--${config.color}-9)` }}
              className={muted ? "opacity-50" : undefined}
              aria-hidden
            />
          </span>
          <span className="shrink-0 text-[11px] tabular-nums">
            {prNumber ? `#${prNumber}` : "PR"}
          </span>
          <span className="min-w-0 flex-1 truncate text-foreground">
            {title ?? entry.task.title}
          </span>
          {tone && (
            <span
              role="img"
              aria-label={CI_LABEL[tone]}
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                CI_DOT_CLASS[tone],
              )}
            />
          )}
          <span className="shrink-0 text-[11px] tabular-nums">
            {formatRelativeTimeShort(entry.task.updated_at)}
          </span>
        </button>
      }
      content={<PrPopoverContent url={entry.url} />}
    />
  );
}

/**
 * The pull requests of a space, beside its feed: every PR a session here
 * opened, grouped by what it needs. It stays whatever the feed's filter says,
 * so "what is shipping" is never a click away.
 */
export function SpacePullRequestsColumn({
  tasks,
  className,
}: {
  tasks: Task[];
  className?: string;
}) {
  const sources = useMemo(() => {
    const seen = new Set<string>();
    const out: { url: string; task: Task }[] = [];
    const byActivity = [...tasks].sort(
      (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at),
    );
    for (const task of byActivity) {
      for (const raw of readPrUrls(task.latest_run?.output)) {
        const parsed = parseHttpsUrl(raw);
        const url =
          parsed?.origin === "https://github.com" ? parsed.href : null;
        if (!url || seen.has(url)) continue;
        seen.add(url);
        out.push({ url, task });
      }
    }
    return out;
  }, [tasks]);
  const urls = useMemo(() => sources.map((entry) => entry.url), [sources]);
  // One batched lookup for the column, so a row is a render and not a request.
  const details = usePrDetailsMap(urls);
  const titles = usePrTitles(urls);
  const groups = useMemo(() => {
    const byGroup: Record<PrGroup, PullRequestEntry[]> = {
      open: [],
      draft: [],
      merged: [],
      closed: [],
      pending: [],
    };
    for (const source of sources) {
      const detail = details[source.url];
      const group = groupOf(detail);
      byGroup[group].push({ ...source, group, details: detail });
    }
    return byGroup;
  }, [sources, details]);

  const total = sources.length;

  return (
    <aside
      className={cn(
        "flex min-h-0 w-[276px] shrink-0 flex-col border-border border-l",
        className,
      )}
      aria-label="Pull requests"
    >
      <div className="flex h-10 shrink-0 items-center justify-between px-3">
        <span className="flex items-center gap-1.5 font-semibold text-[13px]">
          <GitPullRequestIcon size={14} aria-hidden />
          Pull requests
        </span>
        {total > 0 && (
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {total}
          </span>
        )}
      </div>
      <div className="scroll-mask-8 min-h-0 flex-1 overflow-y-auto px-1.5 pb-3">
        {total === 0 ? (
          <p className="px-2 py-1 text-muted-foreground text-xs">
            No pull requests yet. Sessions that open one show it here.
          </p>
        ) : (
          GROUPS.map((group) =>
            groups[group].length === 0 ? null : (
              <div key={group} className="flex flex-col gap-px">
                {GROUP_LABEL[group] ? (
                  <MenuLabel className="px-2">{GROUP_LABEL[group]}</MenuLabel>
                ) : (
                  <div className="h-1.5" />
                )}
                {groups[group].map((entry) => (
                  <PullRequestLine
                    key={entry.url}
                    entry={entry}
                    title={titles[entry.url]}
                    showChecks={group === "open" || group === "draft"}
                    muted={group === "pending"}
                  />
                ))}
              </div>
            ),
          )
        )}
      </div>
    </aside>
  );
}
