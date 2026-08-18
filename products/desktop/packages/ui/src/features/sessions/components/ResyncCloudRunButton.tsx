import { ArrowsClockwise } from "@phosphor-icons/react";
import { isTerminalStatus } from "@posthog/core/cloud-task/schemas";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { Button as QuillButton } from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { useEffect, useRef, useState } from "react";
import { shallow } from "zustand/shallow";
import { useSessionResyncStore } from "../sessionResyncStore";
import { useSessionSelector } from "../useSession";

interface ResyncCloudRunButtonProps {
  taskId: string;
}

/**
 * Escape hatch for a stale cloud stream: tears the watcher down and lets the
 * reconcile effect rebuild it with a fresh subscription and snapshot replay —
 * the same recovery an app reload performs, scoped to this task.
 */
export function ResyncCloudRunButton({ taskId }: ResyncCloudRunButtonProps) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const bump = useSessionResyncStore((s) => s.bump);
  const { isCloud, cloudStatus } = useSessionSelector(
    taskId,
    (session) => ({
      isCloud: session?.isCloud ?? false,
      cloudStatus: session?.cloudStatus ?? null,
    }),
    shallow,
  );
  const [resyncing, setResyncing] = useState(false);
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (resetTimer.current) clearTimeout(resetTimer.current);
    },
    [],
  );

  if (!isCloud || isTerminalStatus(cloudStatus)) return null;

  const handleResync = () => {
    if (resyncing) return;
    setResyncing(true);
    sessionService.stopCloudTaskWatch(taskId);
    bump(taskId);
    // Brief double-click guard; the rebuilt watcher replays a full snapshot,
    // so there is no completion signal to await here.
    resetTimer.current = setTimeout(() => setResyncing(false), 2_000);
  };

  return (
    <Tooltip content="Resync stream" side="bottom">
      <div className="no-drag flex items-center">
        <QuillButton
          variant="outline"
          size="sm"
          aria-label="Resync stream"
          disabled={resyncing}
          onClick={handleResync}
        >
          <ArrowsClockwise
            size={14}
            weight="regular"
            className={resyncing ? "shrink-0 animate-spin" : "shrink-0"}
          />
        </QuillButton>
      </div>
    </Tooltip>
  );
}
