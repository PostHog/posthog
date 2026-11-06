import {
  latestAgentMessage,
  persistedTurnMessage,
} from "@posthog/core/sessions/latestTurnMessage";
import type { Task } from "@posthog/shared/domain-types";
import { useSessionSelector } from "@posthog/ui/features/sessions/useSession";

/**
 * The last thing the agent said on a task, for a surface showing it without
 * opening it.
 *
 * The live session wins where there is one: it has the turn that is streaming
 * right now, which the run's persisted text won't carry until the turn ends. A
 * task this window has never opened has no session, and falls back to what the
 * cloud run wrote when it finished.
 *
 * Costs nothing either way — both sources are already in the renderer, so a
 * card can show this without a request per row.
 */
export function useLatestTurnMessage(
  task: Task | null | undefined,
): string | null {
  const live = useSessionSelector(task?.id, (session) =>
    latestAgentMessage(session?.events),
  );
  return live ?? persistedTurnMessage(task?.latest_run?.output);
}
