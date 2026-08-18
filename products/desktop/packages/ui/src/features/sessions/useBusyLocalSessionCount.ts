import { countBusyLocalSessions } from "@posthog/core/sessions/busyLocalSessions";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";

/** Count of local agent sessions mid-turn, i.e. what an app restart interrupts. */
export function useBusyLocalSessionCount(): number {
  return useSessionStore((state) => countBusyLocalSessions(state.sessions));
}
