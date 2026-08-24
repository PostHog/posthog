const MIN_RATE = 1 / 3;
const MAX_RATE = 3;
const FAST_MS = 30 * 1000;
const NORMAL_START_MS = 2 * 60 * 1000;
const NORMAL_END_MS = 4 * 60 * 1000;
const SLOW_MS = 30 * 60 * 1000;

// Maps a task's duration to an audio playback rate so a quick task rings fast
// (and high-pitched) while a long one drags slow (and low). Anchored at: <=30s
// -> 3x, the 2-4min "normal" band -> 1x, >=30min -> 1/3x, with smooth
// log-interpolation across the two ramps so the rate doesn't jump at the edges.
export function playbackRateForTaskDuration(durationMs: number): number {
  if (!Number.isFinite(durationMs) || durationMs <= FAST_MS) return MAX_RATE;
  if (durationMs >= SLOW_MS) return MIN_RATE;
  if (durationMs >= NORMAL_START_MS && durationMs <= NORMAL_END_MS) return 1;

  if (durationMs < NORMAL_START_MS) {
    const frac =
      (Math.log(durationMs) - Math.log(FAST_MS)) /
      (Math.log(NORMAL_START_MS) - Math.log(FAST_MS));
    return MAX_RATE ** (1 - frac);
  }

  const frac =
    (Math.log(durationMs) - Math.log(NORMAL_END_MS)) /
    (Math.log(SLOW_MS) - Math.log(NORMAL_END_MS));
  return MIN_RATE ** frac;
}
