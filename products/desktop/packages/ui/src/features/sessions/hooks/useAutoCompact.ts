import { decideAutoCompact } from "@posthog/core/sessions/autoCompact";
import type { ContextUsage } from "@posthog/core/sessions/contextUsage";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { toast } from "@posthog/ui/primitives/toast";
import { useEffect, useRef } from "react";

interface AutoCompactArgs {
  usage: ContextUsage | null;
  isCompacting: boolean;
  isRunning: boolean;
  /** The session's own send path, so compaction goes through the same route a
   *  typed `/compact` takes. */
  sendPrompt: (text: string) => Promise<boolean>;
}

/**
 * Compacts the session when its context passes the user's threshold, using the
 * same command a person would type. Silent when the setting is off, which is
 * the default.
 */
export function useAutoCompact({
  usage,
  isCompacting,
  isRunning,
  sendPrompt,
}: AutoCompactArgs): void {
  const thresholdPercent = useSettingsStore(
    (state) => state.autoCompactPercent,
  );
  const armedRef = useRef(true);
  // Held in a ref so a re-render mid-send cannot start a second compaction.
  const sendingRef = useRef(false);

  useEffect(() => {
    const decision = decideAutoCompact({
      thresholdPercent,
      percentage: usage?.percentage ?? null,
      isCompacting,
      isRunning,
      armed: armedRef.current && !sendingRef.current,
    });
    armedRef.current = decision.armed || sendingRef.current;
    if (!decision.compact) return;

    sendingRef.current = true;
    void sendPrompt("/compact")
      .then((sent) => {
        if (!sent) {
          // Re-arm so a rejected send is retried at the next resting point
          // rather than silently disabling the setting for this session.
          armedRef.current = true;
          return;
        }
        toast.info("Compacting the session", {
          description: `The context passed ${thresholdPercent}% of the window.`,
        });
      })
      .finally(() => {
        sendingRef.current = false;
      });
  }, [thresholdPercent, usage, isCompacting, isRunning, sendPrompt]);
}
