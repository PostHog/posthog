import type { RecordingExport } from "@posthog/api-client/posthog-client";

export function clipTimeForMoment(
  clip: RecordingExport,
  sessionOffsetSeconds: number,
): number | null {
  if (clip.segments.length === 0) {
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
