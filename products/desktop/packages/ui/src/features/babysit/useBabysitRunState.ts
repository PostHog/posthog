import { NotAuthenticatedError, readPrUrls } from "@posthog/shared";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import { useSessionForTask } from "@posthog/ui/features/sessions/useSession";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation } from "@tanstack/react-query";
import { useCallback } from "react";

export type BabysitMode = "ask" | "auto" | "always" | "never";

export type BabysitUiState =
  | "unavailable"
  | "off"
  | "stopped"
  | "proposed"
  | "attention"
  | "watching";

export interface BabysitRunState {
  uiState: BabysitUiState;
  runId: string | undefined;
  staged: Record<string, unknown> | null;
  wakeUps: number;
}

const MODES: readonly BabysitMode[] = ["ask", "auto", "always", "never"];

export function deriveBabysitUiState(
  state: Record<string, unknown> | null | undefined,
): BabysitUiState {
  const mode = state?.babysit_mode;
  if (typeof mode !== "string" || !MODES.includes(mode as BabysitMode)) {
    return "unavailable";
  }
  const armed = state?.babysit_armed === true;
  if (state?.babysit_stopped === true) return "stopped";
  if (state?.babysit_staged) return "attention";
  if (mode === "never" && !armed) return "off";
  if (mode === "ask" && !armed) return "proposed";
  return "watching";
}

export function useBabysitRunState(
  taskId: string | undefined,
  prUrl: string | undefined,
): BabysitRunState {
  const session = useSessionForTask(taskId);
  const { data: tasks = [] } = useTasks();

  const task = taskId
    ? tasks.find((candidate) => candidate.id === taskId)
    : undefined;
  const latestRun = task?.latest_run;
  const runOwnsPr =
    !prUrl || !latestRun
      ? Boolean(latestRun)
      : readPrUrls(latestRun.output).includes(prUrl) ||
        readPrUrls(session?.cloudOutput).includes(prUrl);

  const state = session?.cloudState ?? latestRun?.state ?? null;
  const runId = session?.taskRunId ?? latestRun?.id;

  if (!runOwnsPr || !runId) {
    return {
      uiState: "unavailable",
      runId: undefined,
      staged: null,
      wakeUps: 0,
    };
  }

  const staged =
    state && typeof state.babysit_staged === "object"
      ? (state.babysit_staged as Record<string, unknown> | null)
      : null;
  const wakeUps =
    typeof state?.babysit_wake_ups === "number" ? state.babysit_wake_ups : 0;

  return { uiState: deriveBabysitUiState(state), runId, staged, wakeUps };
}

function useBabysitMutation(
  taskId: string | undefined,
  runId: string | undefined,
  action: "approve" | "stop",
) {
  const mutate = useCallback(async () => {
    const client = await getAuthenticatedClient();
    if (!client) throw new NotAuthenticatedError();
    if (!taskId || !runId) return;
    if (action === "approve") {
      await client.approveBabysit(taskId, runId);
    } else {
      await client.stopBabysit(taskId, runId);
    }
  }, [taskId, runId, action]);

  return useMutation({
    mutationFn: mutate,
    onError: () => {
      toast.error("Couldn't update babysitting. The run may have ended.");
    },
  });
}

export function useStartBabysit(
  taskId: string | undefined,
  runId: string | undefined,
) {
  return useBabysitMutation(taskId, runId, "approve");
}

export function useStopBabysit(
  taskId: string | undefined,
  runId: string | undefined,
) {
  return useBabysitMutation(taskId, runId, "stop");
}
