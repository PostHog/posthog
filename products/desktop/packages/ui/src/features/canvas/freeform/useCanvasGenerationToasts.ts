import { useServiceOptional } from "@posthog/di/react";
import {
  type CanvasTerminalStatus,
  hasCanvasGenerationStarted,
  isCanvasGenerating,
  resolveCanvasGenerationStatus,
} from "@posthog/ui/features/canvas/freeform/canvasGenerationStatus";
import { useCanvasGenerationTrackerStore } from "@posthog/ui/features/canvas/stores/canvasGenerationTrackerStore";
import { NotificationBus } from "@posthog/ui/features/notifications/notifications";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQueries } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

// Poll cadence for the run status of a tracked generation task. Matches the
// canvas record poll in FreeformCanvasView so the toast and the in-view state
// land together.
const POLL_MS = 4000;

// Hand a finished canvas generation to the notification bus, which decides
// whether to suppress (user is on the canvas), toast (focused elsewhere), or
// fire a native OS notification (app backgrounded) — and threads the canvas
// target so any click lands back on the canvas.
function emitCanvasGenerationNotification(
  bus: NotificationBus,
  entry: { channelId: string; dashboardId: string; name: string },
  status: CanvasTerminalStatus,
): void {
  const name = entry.name.trim() || "Canvas";
  const target = {
    kind: "canvas" as const,
    channelId: entry.channelId,
    dashboardId: entry.dashboardId,
  };

  if (status === "completed") {
    bus.notify({
      body: `${name} is ready`,
      target,
      toast: { level: "success", description: "Generation finished." },
    });
  } else if (status === "failed") {
    bus.notify({
      body: `${name} generation failed`,
      target,
      toast: {
        level: "error",
        description: "The agent couldn't finish building this canvas.",
      },
    });
  }
  // "cancelled" is user-initiated — stay silent.
}

// Watches every canvas generation started in this client (registered in the
// tracker store) and fires a toast — with a link to the canvas — the moment each
// one stops generating. Mounted on the persistent channel layout so it keeps
// watching after the user navigates to another canvas: the whole point is to
// call them back when a backgrounded generation lands.
//
// Completion is read from the same signal the canvas view uses (isCanvasGenerating:
// the live ACP session for local runs, cloudStatus for cloud) rather than the
// dashboard's generationTaskId, which is never cleared for freeform canvases.
export function useCanvasGenerationToasts(): void {
  const tracked = useCanvasGenerationTrackerStore((s) => s.tracked);
  const untrack = useCanvasGenerationTrackerStore((s) => s.untrack);
  // The bus is a container singleton (stable identity); capture in a ref so the
  // status-keyed effect reads it without listing it as a dependency. Optional so
  // hosts that don't bind it (web) simply no-op instead of throwing.
  const bus = useServiceOptional<NotificationBus>(NotificationBus);
  const busRef = useRef(bus);
  busRef.current = bus;

  const taskIds = useMemo(() => Object.keys(tracked), [tracked]);

  const details = useQueries({
    queries: taskIds.map((id) => ({
      ...taskDetailQuery(id),
      refetchInterval: POLL_MS,
    })),
  });

  // The live ACP sessions — for local runs this, not the run record, is what
  // tells us generation has actually finished.
  const sessions = useSessionStore((s) => s.sessions);
  const taskIdIndex = useSessionStore((s) => s.taskIdIndex);

  // Compute the "still generating?" signal per tracked task each render.
  const states = taskIds.map((id, i) => {
    const runId = taskIdIndex[id];
    const session = runId ? sessions[runId] : undefined;
    const latestRun = details[i]?.data?.latest_run;
    const generating = isCanvasGenerating({
      genTaskId: id,
      genTaskLoading: details[i]?.isLoading ?? false,
      latestRun,
      session,
    });
    return { id, generating, latestRun, session };
  });

  // A stable signature so the transition effect only runs on real changes.
  const sig = states
    .map(
      (s) =>
        `${s.id}:${s.generating ? 1 : 0}:${s.latestRun?.status ?? ""}:${s.session?.status ?? ""}:${s.session?.cloudStatus ?? ""}:${s.session?.isPromptPending ? 1 : 0}`,
    )
    .join("|");

  const statesRef = useRef(states);
  statesRef.current = states;
  // Tasks we've confirmed actually started running — only an armed task can
  // toast on finishing, so the create→connect gap can't fire a false toast.
  const armedRef = useRef<Set<string>>(new Set());
  // Tasks already toasted, so a re-run can never double-fire.
  const toastedRef = useRef<Set<string>>(new Set());

  // biome-ignore lint/correctness/useExhaustiveDependencies: sig is the trigger; states/store are read fresh (states via ref) when it changes.
  useEffect(() => {
    for (const st of statesRef.current) {
      if (
        hasCanvasGenerationStarted({
          latestRun: st.latestRun,
          session: st.session,
        })
      ) {
        armedRef.current.add(st.id);
      }

      // A task only toasts once it has demonstrably run and is no longer
      // generating.
      if (
        !armedRef.current.has(st.id) ||
        st.generating ||
        toastedRef.current.has(st.id)
      ) {
        continue;
      }

      toastedRef.current.add(st.id);
      const entry = useCanvasGenerationTrackerStore.getState().tracked[st.id];
      if (entry && busRef.current) {
        emitCanvasGenerationNotification(
          busRef.current,
          entry,
          resolveCanvasGenerationStatus({
            latestRun: st.latestRun,
            session: st.session,
          }),
        );
      }
      // Stop tracking (and polling) this task now that it's done.
      untrack(st.id);
    }
  }, [sig, untrack]);
}

// Renders nothing; exists only to host useCanvasGenerationToasts so the frequent
// session-driven re-renders it subscribes to stay isolated here instead of
// re-rendering whatever layout mounts it.
export function CanvasGenerationToaster(): null {
  useCanvasGenerationToasts();
  return null;
}
