import type { RecordingExport } from "@posthog/api-client/posthog-client";

/**
 * Map a moment in the session onto a time in the rendered clip.
 *
 * A render drops the idle stretches of a session, so clip time runs behind
 * session time by however much idle time came before the moment: a moment 7
 * minutes into a session can sit 4 minutes into the clip. The render records
 * where each stretch landed, so walk those rather than subtracting offsets.
 *
 * A moment that fell inside a dropped stretch has no frame of its own and
 * resolves to the first frame after it. Null means the clip does not reach the
 * moment, which happens when the render stopped early.
 */
export function clipTimeForMoment(
  clip: RecordingExport,
  sessionOffsetSeconds: number,
): number | null {
  if (clip.segments.length === 0) {
    // The render kept every stretch, so the clip runs in session order from
    // wherever its window opens.
    const clipTime = sessionOffsetSeconds - clip.startOffsetSeconds;
    if (clipTime < 0) return null;
    if (
      clip.clipDurationSeconds != null &&
      clipTime > clip.clipDurationSeconds
    ) {
      return null;
    }
    return clipTime;
  }

  for (const segment of clip.segments) {
    if (sessionOffsetSeconds < segment.sessionFromSeconds) {
      return segment.clipFromSeconds;
    }
    const sessionTo = segment.sessionToSeconds ?? segment.sessionFromSeconds;
    if (sessionOffsetSeconds <= sessionTo) {
      if (!segment.active) return segment.clipFromSeconds;
      const intoSegment = sessionOffsetSeconds - segment.sessionFromSeconds;
      return Math.min(
        segment.clipFromSeconds + intoSegment,
        segment.clipToSeconds,
      );
    }
  }
  return null;
}
