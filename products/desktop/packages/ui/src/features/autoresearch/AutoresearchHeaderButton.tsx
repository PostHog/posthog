import { ChartLineUp } from "@phosphor-icons/react";
import type { AutoresearchService } from "@posthog/core/autoresearch/autoresearch";
import { AUTORESEARCH_SERVICE } from "@posthog/core/autoresearch/identifiers";
import { useServiceOptional } from "@posthog/di/react";
import { Button } from "@posthog/quill";
import { useEffect } from "react";
import { Tooltip } from "../../primitives/Tooltip";
import { usePanelLayoutStore } from "../panels/panelLayoutStore";
import { useAutoresearchEnabled } from "./useAutoresearchEnabled";
import {
  useActiveAutoresearchRun,
  useAutoresearchRuns,
} from "./useAutoresearchStore";

interface AutoresearchHeaderButtonProps {
  taskId: string;
}

/**
 * Task-header shortcut to the autoresearch dashboard. Only rendered for
 * tasks that have a run. Autoresearch tasks are created from the composer,
 * not retrofitted onto existing tasks.
 */
export function AutoresearchHeaderButton({
  taskId,
}: AutoresearchHeaderButtonProps) {
  const service = useServiceOptional<AutoresearchService>(AUTORESEARCH_SERVICE);
  const openAutoresearchTab = usePanelLayoutStore(
    (state) => state.openAutoresearchTab,
  );
  const runs = useAutoresearchRuns(taskId);
  const activeRun = useActiveAutoresearchRun(taskId);

  const enabled = useAutoresearchEnabled();

  // Runs persist across app restarts; without this the entry point would
  // vanish for restored tasks until something else loads their history.
  // Flag-gated: ungated users never hydrate, so the button (which needs
  // hydrated runs) stays hidden for them.
  useEffect(() => {
    if (service && enabled) void service.hydrateTask(taskId);
  }, [service, enabled, taskId]);

  const isLive =
    activeRun?.status === "running" ||
    activeRun?.status === "paused" ||
    activeRun?.status === "interrupted";
  const needsAttention = activeRun?.status === "interrupted";

  if (!service || runs.length === 0) return null;

  return (
    <Tooltip
      content={
        needsAttention
          ? "Autoresearch (interrupted)"
          : isLive
            ? "Autoresearch (running)"
            : "Autoresearch"
      }
      side="bottom"
    >
      <Button
        size="icon-sm"
        variant="outline"
        aria-label="Open autoresearch dashboard"
        onClick={() => openAutoresearchTab(taskId)}
        className="relative"
      >
        <ChartLineUp size={16} />
        {isLive && (
          <span
            className={`absolute top-0.5 right-0.5 h-1.5 w-1.5 rounded-full ${
              needsAttention ? "bg-(--orange-9)" : "bg-(--blue-9)"
            }`}
          />
        )}
      </Button>
    </Tooltip>
  );
}
