import type {
  RecordingClipSegment,
  RecordingExport,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { clipTimeForMoment } from "./recordingClipTime";

function makeClip(overrides: Partial<RecordingExport> = {}): RecordingExport {
  return {
    id: 1,
    startOffsetSeconds: 0,
    endOffsetSeconds: null,
    clipDurationSeconds: null,
    truncated: false,
    segments: [],
    ...overrides,
  };
}

function segment(
  sessionFrom: number,
  sessionTo: number,
  clipFrom: number,
  clipTo: number,
  active = true,
): RecordingClipSegment {
  return {
    sessionFromSeconds: sessionFrom,
    sessionToSeconds: sessionTo,
    clipFromSeconds: clipFrom,
    clipToSeconds: clipTo,
    active,
  };
}

describe("clipTimeForMoment", () => {
  describe("a render that kept every stretch", () => {
    it.each([
      ["a whole-session clip", 0, 120, 120],
      ["a clip whose window opens late", 100, 160, 60],
    ])("maps %s", (_label, startOffset, sessionOffset, expected) => {
      const clip = makeClip({
        startOffsetSeconds: startOffset,
        clipDurationSeconds: 300,
      });
      expect(clipTimeForMoment(clip, sessionOffset)).toBe(expected);
    });

    it.each([
      ["the moment sits before the window", 100, 40],
      ["the moment sits past the clip's end", 0, 400],
    ])("returns null when %s", (_label, startOffset, sessionOffset) => {
      const clip = makeClip({
        startOffsetSeconds: startOffset,
        clipDurationSeconds: 300,
      });
      expect(clipTimeForMoment(clip, sessionOffset)).toBeNull();
    });
  });

  describe("a render that dropped idle stretches", () => {
    // 0-60s active, 60-300s idle and dropped, 300-360s active. A 5:00 session
    // renders as a 2:00 clip.
    const clip = makeClip({
      clipDurationSeconds: 120,
      segments: [
        segment(0, 60, 0, 60),
        segment(60, 300, 60, 60, false),
        segment(300, 360, 60, 120),
      ],
    });

    it.each([
      ["inside the first active stretch", 30, 30],
      ["at the boundary into the dropped stretch", 60, 60],
      ["inside the second active stretch", 330, 90],
      ["at the very end of the clip", 360, 120],
    ])("maps a moment %s", (_label, sessionOffset, expected) => {
      expect(clipTimeForMoment(clip, sessionOffset)).toBe(expected);
    });

    it("resolves a moment inside a dropped stretch to the next frame", () => {
      expect(clipTimeForMoment(clip, 200)).toBe(60);
    });

    it("maps a moment past the clip's length, which a subtraction would reject", () => {
      // The bug this replaced: 330s in the session is only 90s into the clip,
      // but a session-minus-start subtraction reads 330 > 120 and gives up.
      const target = clipTimeForMoment(clip, 330);
      expect(target).not.toBeNull();
      expect(target).toBeLessThan(clip.clipDurationSeconds ?? 0);
    });

    it("returns null for a moment the render never reached", () => {
      expect(clipTimeForMoment(clip, 420)).toBeNull();
    });

    it("returns the clip start for a moment before the first stretch", () => {
      const late = makeClip({
        segments: [segment(100, 160, 0, 60)],
      });
      expect(clipTimeForMoment(late, 40)).toBe(0);
    });
  });
});
