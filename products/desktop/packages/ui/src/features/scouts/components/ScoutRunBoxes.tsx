import type { ScoutRun } from "@posthog/api-client/posthog-client";
import {
  deriveRunOutcome,
  formatRunDuration,
  runDurationSeconds,
  type ScoutRunOutcome,
  scoutRunOutcomeLabel,
} from "@posthog/core/scouts/scoutPresentation";
import { formatRelativeTimeLong } from "@posthog/shared";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { Flex, Text, Tooltip } from "@radix-ui/themes";

// Quiet is the common, healthy baseline so it recedes to gray; saturated
// color only means something happened – iris payoff, red/amber trouble.
const OUTCOME_BOX_CLASS: Record<ScoutRunOutcome, string> = {
  emitted: "bg-(--iris-9)",
  quiet: "bg-(--gray-5)",
  error: "bg-(--red-9)",
  timed_out: "bg-(--amber-9)",
  running: "bg-(--blue-9) animate-pulse",
  stuck: "bg-(--red-9) animate-pulse",
  queued: "border border-(--gray-7) bg-transparent",
  unknown: "bg-(--gray-6)",
};

const MAX_BOXES = 24;
const BOX_CLASS =
  "block h-3 w-2 rounded-[2px] transition-transform duration-100 hover:scale-y-125 hover:ring-(--gray-8) hover:ring-1";

function runTooltip(run: ScoutRun, now: Date): string {
  const parts = [scoutRunOutcomeLabel(run, now)];
  const duration = formatRunDuration(runDurationSeconds(run, now));
  if (duration) parts.push(duration);
  if (run.started_at) {
    parts.push(formatRelativeTimeLong(new Date(run.started_at).getTime()));
  }
  return parts.join(" · ");
}

/**
 * One small box per run in the visible window, oldest on the left. Each box
 * opens the backing task run in PostHog cloud; runs without a task link are
 * tooltip-only.
 */
export function ScoutRunBoxes({ runs }: { runs: ScoutRun[] }) {
  if (runs.length === 0) return null;
  const visible = runs.slice(-MAX_BOXES);
  const hidden = runs.length - visible.length;
  const now = new Date();

  return (
    <Flex align="center" gap="2" className="shrink-0">
      {hidden > 0 ? (
        <Text className="text-[10px] text-gray-9">+{hidden}</Text>
      ) : null}
      <Flex align="center" gap="1">
        {visible.map((run) => {
          const outcome = deriveRunOutcome(run, now);
          const boxClass = `${BOX_CLASS} ${OUTCOME_BOX_CLASS[outcome]}`;
          const taskRunUrl = run.task_url ? getPostHogUrl(run.task_url) : null;
          if (taskRunUrl) {
            const tooltip = `${runTooltip(run, now)} · open task run in PostHog`;
            return (
              <Tooltip key={run.run_id} content={tooltip}>
                <a
                  href={taskRunUrl}
                  target="_blank"
                  rel="noreferrer"
                  className={boxClass}
                >
                  <span className="sr-only">Run {tooltip}</span>
                </a>
              </Tooltip>
            );
          }
          const tooltip = runTooltip(run, now);
          return (
            <Tooltip key={run.run_id} content={tooltip}>
              <span className={boxClass}>
                <span className="sr-only">Run {tooltip}</span>
              </span>
            </Tooltip>
          );
        })}
      </Flex>
    </Flex>
  );
}
