import {
  getPrVisualConfig,
  parsePrNumber,
} from "@posthog/core/git-interaction/prStatus";
import { cn, MenuLabel, Skeleton } from "@posthog/quill";
import { readPrUrls } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { feedDayLabel } from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { SideColumnHeading } from "@posthog/ui/features/canvas/components/work/SideColumnHeading";
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

function isLive(details: PrStateDetails | undefined): boolean {
  return !!details && !details.merged && details.state !== "closed";
}

function PullRequestLine({
  entry,
  title,
}: {
  entry: PullRequestEntry;
  title: string | undefined;
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
    <button
      type="button"
      title={title ?? entry.task.title}
      className="flex h-7 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left font-medium text-[12px] text-muted-foreground leading-snug transition-colors hover:bg-fill-hover hover:text-foreground"
      onClick={() => openExternalUrl(entry.url)}
    >
      <span className="flex size-3.5 shrink-0 items-center justify-center">
        <Icon
          size={13}
          style={settled ? { color: `var(--${config.color}-9)` } : undefined}
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
          className={cn("size-1.5 shrink-0 rounded-full", CI_DOT_CLASS[tone])}
        />
      )}
    </button>
  );
}

export function SpacePullRequestsColumn({
  tasks,
  isLoading = false,
  className,
}: {
  tasks: Task[];
  isLoading?: boolean;
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

  return (
    <section
      className={cn("flex flex-col", className)}
      aria-label="Pull requests"
    >
      <SideColumnHeading>Pull requests</SideColumnHeading>
      <div className="px-1.5 pb-3">
        {isLoading && sources.length === 0 ? (
          <div className="flex flex-col gap-2 px-2 py-2">
            <Skeleton className="h-3.5 w-16" />
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-4/5" />
            <Skeleton className="h-3.5 w-3/5" />
          </div>
        ) : sources.length === 0 ? (
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
                />
              ))}
            </div>
          ))
        )}
      </div>
    </section>
  );
}
