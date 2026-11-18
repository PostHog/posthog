import { CaretRightIcon } from "@phosphor-icons/react";
import type { ScoutRun } from "@posthog/api-client/posthog-client";
import {
  deriveRunOutcome,
  formatRunDuration,
  normalizeRunStatus,
  runDurationSeconds,
  type ScoutRunOutcome,
  scoutRunOutcomeLabel,
  scoutRunOutputCount,
  scoutSummarySentence,
} from "@posthog/core/scouts/scoutPresentation";
import { Badge } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { useState } from "react";
import { ScoutRunReportLinks } from "./ScoutRunReportLinks";
import { ScoutTaskRunLink } from "./ScoutTaskRunLink";

const OUTCOME_DOT: Record<ScoutRunOutcome, string> = {
  emitted: "bg-(--iris-9)",
  quiet: "border-[1.5px] border-(--gray-7)",
  error: "bg-(--red-9)",
  timed_out: "bg-(--amber-9)",
  running: "bg-(--blue-9) animate-pulse",
  stuck: "bg-(--red-9) animate-pulse",
  queued: "border border-dashed border-(--gray-7)",
  unknown: "bg-(--gray-6)",
};

/**
 * One row per run. Collapsed, it is a single line: when, how long, the first
 * sentence of the close-out, and the outcome. Expanded, the full close-out.
 */
export function ScoutRunListItem({
  run,
  defaultExpanded = false,
}: {
  run: ScoutRun;
  defaultExpanded?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const now = new Date();
  const taskRunUrl = run.task_url ? getPostHogUrl(run.task_url) : null;
  const status = normalizeRunStatus(run.status);
  const outcome = deriveRunOutcome(run, now);
  const duration = formatRunDuration(runDurationSeconds(run, now));
  const emitted = scoutRunOutputCount(run);
  const title = scoutSummarySentence(run.summary);

  return (
    <div className="border-(--gray-4) border-b px-4 py-2.5 last:border-b-0">
      <button
        type="button"
        onClick={() => {
          const next = !expanded;
          setExpanded(next);
          track(ANALYTICS_EVENTS.SCOUT_ACTION, {
            action_type: next ? "expand_run" : "collapse_run",
            surface: "scout_detail",
            skill_name: run.skill_name,
            run_id: run.run_id,
            run_status: status,
            emitted_count: emitted,
          });
        }}
        aria-expanded={expanded}
        className="flex w-full min-w-0 select-none items-center gap-2 rounded-sm text-left outline-none focus-visible:ring-(--gray-8) focus-visible:ring-1"
      >
        <CaretRightIcon
          size={11}
          className={`shrink-0 text-gray-9 transition-transform duration-150 motion-reduce:transition-none ${expanded ? "rotate-90" : ""}`}
        />
        <span
          className={`inline-block h-2 w-2 shrink-0 rounded-full ${OUTCOME_DOT[outcome]}`}
          aria-hidden
        />
        <RelativeTimestamp
          timestamp={run.started_at}
          className="shrink-0 text-[12px] text-gray-12"
        />
        {duration ? (
          <span className="shrink-0 text-[11.5px] text-gray-10">
            · {duration}
          </span>
        ) : null}
        {outcome === "error" || outcome === "timed_out" ? (
          <span
            className={`shrink-0 text-[11.5px] ${outcome === "timed_out" ? "text-(--amber-11)" : "text-(--red-11)"}`}
          >
            · {outcome === "timed_out" ? "timed out" : "failed"}
          </span>
        ) : null}
        {outcome === "stuck" ? (
          <span className="shrink-0 text-(--red-11) text-[11.5px]">
            · running past the deadline
          </span>
        ) : null}
        {["running", "queued", "unknown"].includes(outcome) ? (
          <span className="shrink-0 text-[11.5px] text-gray-11">
            {scoutRunOutcomeLabel(run, now)}
          </span>
        ) : null}
        {!expanded && title ? (
          <span className="min-w-0 flex-1 truncate pl-1 text-[12px] text-gray-11">
            {title}
          </span>
        ) : (
          <span className="flex-1" />
        )}
        {emitted > 0 ? (
          <Badge variant="info" className="shrink-0">
            {emitted} output{emitted === 1 ? "" : "s"}
          </Badge>
        ) : status === "completed" ? (
          <span className="shrink-0 text-[11.5px] text-gray-9">quiet</span>
        ) : null}
      </button>
      {expanded ? (
        run.summary ? (
          <div className="mt-2 text-pretty break-words pl-[21px] text-[12.5px] text-gray-11 leading-snug [&_code]:text-[11px] [&_p:last-child]:mb-0 [&_p]:mb-1 [&_pre]:text-[11px]">
            <MarkdownRenderer
              content={run.summary}
              componentsOverride={{ img: ({ alt }) => <span>{alt}</span> }}
            />
          </div>
        ) : status === "failed" ? (
          <p className="mt-2 pl-[21px] text-[12.5px] text-gray-10 italic leading-snug">
            No summary. The run ended before it wrote a close-out. The task run
            in PostHog is the only diagnostic.
          </p>
        ) : null
      ) : null}
      {expanded ? (
        <div className="mt-2 pl-[21px]">
          <ScoutRunReportLinks run={run} />
        </div>
      ) : null}
      {expanded && taskRunUrl ? (
        <div className="mt-2 flex justify-end border-(--gray-4) border-t pt-2 text-[11px] text-gray-10">
          <ScoutTaskRunLink
            run={run}
            taskRunUrl={taskRunUrl}
            runStatus={status}
          />
        </div>
      ) : null}
    </div>
  );
}
