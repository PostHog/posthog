import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import type { ScoutRun } from "@posthog/api-client/posthog-client";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { track } from "@posthog/ui/shell/analytics";

/**
 * "Open task run" link to a scout run in PostHog Cloud, shared by the scout
 * detail run list and the signals section. Callers resolve the URL (and decide
 * the no-URL fallback); `runStatus` is included in analytics when known.
 */
export function ScoutTaskRunLink({
  run,
  taskRunUrl,
  runStatus,
}: {
  run: ScoutRun;
  taskRunUrl: string;
  runStatus?: string;
}) {
  return (
    <a
      href={taskRunUrl}
      target="_blank"
      rel="noreferrer"
      onClick={() =>
        track(ANALYTICS_EVENTS.SCOUT_ACTION, {
          action_type: "open_task_run",
          surface: "scout_detail",
          skill_name: run.skill_name,
          run_id: run.run_id,
          ...(runStatus ? { run_status: runStatus } : {}),
        })
      }
      className="inline-flex shrink-0 items-center gap-1 text-[11px] text-accent-11 no-underline hover:text-accent-12"
    >
      Open task run
      <ArrowSquareOutIcon size={11} />
    </a>
  );
}
