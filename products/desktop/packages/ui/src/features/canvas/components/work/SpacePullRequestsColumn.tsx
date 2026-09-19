import { GitPullRequestIcon } from "@phosphor-icons/react";
import {
  getPrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import {
  cn,
  MenuLabel,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@posthog/quill";
import { readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  feedDayLabel,
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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/** How long the pointer may travel between a row and its card before it closes. */
const CARD_CLOSE_DELAY_MS = 120;

interface PullRequestEntry {
  url: string;
  task: Task;
  details: PrStateDetails | undefined;
}

interface PullRequestDay {
  label: string;
  entries: PullRequestEntry[];
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

/** A PR still open is the only one whose CI is worth a request. */
function isLive(details: PrStateDetails | undefined): boolean {
  return !!details && !details.merged && details.state !== "closed";
}

/**
 * One pull request on one line: lifecycle glyph, number, title, CI, age. Its
 * state, CI detail and the session behind it live in the hover card the feed's
 * PR chips already open. Click opens GitHub.
 */
function PullRequestLine({
  entry,
  title,
  open,
  onOpen,
  onClose,
}: {
  entry: PullRequestEntry;
  title: string | undefined;
  /** The column opens one card at a time, so a row never owns this. */
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
}) {
  const live = isLive(entry.details);
  const checks = usePrChecks(live ? entry.url : null);
  const tone = ciTone(checks.data);
  const config = getPrVisualConfig(
    entry.details?.state ?? "open",
    entry.details?.merged ?? false,
    entry.details?.draft ?? false,
  );
  const Icon = getPrVisualIcon(config.icon);
  const prNumber = parsePrNumber(entry.url);
  const settled = entry.details !== undefined;
  return (
    <Popover open={open} onOpenChange={(next) => !next && onClose()}>
      <PopoverTrigger
        onMouseEnter={onOpen}
        onMouseLeave={onClose}
        render={
          <button
            type="button"
            className="flex h-7 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left font-medium text-[12px] text-muted-foreground leading-snug transition-colors hover:bg-fill-hover hover:text-foreground"
            onClick={() => openExternalUrl(entry.url)}
          >
            <span className="flex size-3.5 shrink-0 items-center justify-center">
              <Icon
                size={13}
                style={
                  settled ? { color: `var(--${config.color}-9)` } : undefined
                }
                className={settled ? undefined : "opacity-50"}
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
          </button>
        }
      />
      <PopoverContent
        className="w-auto gap-0 p-2"
        onMouseEnter={onOpen}
        onMouseLeave={onClose}
      >
        <PrPopoverContent url={entry.url} />
      </PopoverContent>
    </Popover>
  );
}

/**
 * The pull requests of a space, beside its feed: every PR a session here
 * opened, newest day first, so the column reads in the same order as the log
 * next to it.
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
  const days = useMemo<PullRequestDay[]>(() => {
    const now = new Date();
    const out: PullRequestDay[] = [];
    for (const source of sources) {
      const label = feedDayLabel(source.task.updated_at, now);
      const entry = { ...source, details: details[source.url] };
      const last = out[out.length - 1];
      if (last?.label === label) last.entries.push(entry);
      else out.push({ label, entries: [entry] });
    }
    return out;
  }, [sources, details]);

  // One card for the whole column. A card per row left two of them on screen
  // at once while the pointer crossed between rows.
  const [openUrl, setOpenUrl] = useState<string | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  useEffect(() => () => clearTimeout(closeTimer.current), []);
  const openCard = useCallback((url: string) => {
    clearTimeout(closeTimer.current);
    setOpenUrl(url);
  }, []);
  const closeCard = useCallback(() => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(
      () => setOpenUrl(null),
      CARD_CLOSE_DELAY_MS,
    );
  }, []);

  return (
    <aside
      className={cn(
        "flex min-h-0 w-[276px] shrink-0 flex-col border-border border-l",
        className,
      )}
      aria-label="Pull requests"
    >
      <div className="flex h-10 shrink-0 items-center px-3">
        <span className="flex items-center gap-1.5 font-semibold text-[13px]">
          <GitPullRequestIcon size={14} aria-hidden />
          Pull requests
        </span>
      </div>
      <div className="scroll-mask-8 min-h-0 flex-1 overflow-y-auto px-1.5 pb-3">
        {sources.length === 0 ? (
          <p className="px-2 py-1 text-[12px] text-muted-foreground">
            No pull requests yet. Sessions that open one show it here.
          </p>
        ) : (
          days.map((day) => (
            <div key={day.label} className="flex flex-col gap-px">
              <MenuLabel className="px-2">{day.label}</MenuLabel>
              {day.entries.map((entry) => (
                <PullRequestLine
                  key={entry.url}
                  entry={entry}
                  title={titles[entry.url]}
                  open={openUrl === entry.url}
                  onOpen={() => openCard(entry.url)}
                  onClose={closeCard}
                />
              ))}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
