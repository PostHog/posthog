import {
  type ContextBreakdown,
  type ContextUsage,
  createContextUsageTracker,
} from "@posthog/core/sessions/contextUsage";
import type { AcpMessage } from "@posthog/shared";
import { useMemo, useRef } from "react";

export type { ContextBreakdown, ContextUsage };

export function useContextUsage(events: AcpMessage[]): ContextUsage | null {
  const trackerRef = useRef<ReturnType<
    typeof createContextUsageTracker
  > | null>(null);
  trackerRef.current ??= createContextUsageTracker();
  const tracker = trackerRef.current;
  return useMemo(() => tracker.update(events), [events, tracker]);
}
