import { decideAutoCompact } from "@posthog/core/sessions/autoCompact";
import type { ContextUsage } from "@posthog/core/sessions/contextUsage";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { toast } from "@posthog/ui/primitives/toast";
import { useEffect, useRef } from "react";

export interface AutoCompactArgs {
  /** Identifies the session the latch belongs to. The view can swap sessions
   *  without remounting, so the latch resets when this changes. */
  sessionKey: string;
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
  sessionKey,
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

  // This view can receive a different session without remounting, so the latch
  // is scoped to the session by hand. Without this reset the old session's
  // disarmed latch would carry over and suppress the new session's compaction.
  const sessionKeyRef = useRef(sessionKey);
  if (sessionKeyRef.current !== sessionKey) {
    sessionKeyRef.current = sessionKey;
    armedRef.current = true;
    sendingRef.current = false;
  }

  useEffect(() => {
    // While a send is in flight the latch is already held. A re-render here
    // must not recompute it: writing the decision back mid-send would rearm the
    // latch the fire just opened and start a second compaction once the session
    // settles — the loop decideAutoCompact is written to prevent.
    if (sendingRef.current) return;

    const decision = decideAutoCompact({
      thresholdPercent,
      percentage: usage?.percentage ?? null,
      isCompacting,
      isRunning,
      armed: armedRef.current,
    });
    armedRef.current = decision.armed;
    if (!decision.compact) return;

    sendingRef.current = true;
    // The session can change while the send is in flight; the completion must
    // not touch the latch or toast of whatever session is shown by then.
    const sentForKey = sessionKey;
    void sendPrompt("/compact")
      .then((sent) => {
        if (sessionKeyRef.current !== sentForKey) return;
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
        if (sessionKeyRef.current === sentForKey) {
          sendingRef.current = false;
        }
      });
  }, [
    sessionKey,
    thresholdPercent,
    usage,
    isCompacting,
    isRunning,
    sendPrompt,
  ]);
}
