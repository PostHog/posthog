import type {
  SpeechKind,
  SpeechSource,
} from "@posthog/core/speech/identifiers";
import type { SpokenFocusMode } from "@posthog/ui/features/settings/settingsStore";
import type { NotificationChannel } from "./routeNotification";

export type { SpeechKind, SpeechSource };

export interface SpeechGateSettings {
  enabled: boolean;
  needsInput: boolean;
  completion: boolean;
  progress: boolean;
  focusMode: SpokenFocusMode;
}

/**
 * Whether a spoken line should play, given who authored it, the focus-routing
 * channel (from routeNotification) and the user's spoken-notification
 * settings. Pure so the policy is exhaustively unit-tested without the DI
 * graph.
 *
 * Agent needs-input lines ignore focus mode entirely — a blocker is the whole
 * point of the feature. Backstop lines never play over the task the user is
 * already viewing: the permission dialog (or finished turn) is on screen, and
 * consecutive permission prompts would otherwise narrate every approval click.
 */
export function shouldSpeak(
  kind: SpeechKind,
  source: SpeechSource,
  channel: NotificationChannel,
  s: SpeechGateSettings,
): boolean {
  if (!s.enabled) return false;

  const kindEnabled =
    kind === "needs_input"
      ? s.needsInput
      : kind === "done"
        ? s.completion
        : s.progress;
  if (!kindEnabled) return false;

  if (source === "backstop" && channel === "suppress") return false;

  if (kind === "needs_input") return true;

  switch (s.focusMode) {
    case "always":
      return true;
    case "unviewed_task":
      return channel !== "suppress";
    case "app_unfocused":
      return channel === "native";
  }
}
