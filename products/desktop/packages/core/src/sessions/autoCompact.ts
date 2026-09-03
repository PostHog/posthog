/**
 * Compacting a session earlier than the model would on its own.
 *
 * The model already compacts near the context limit. Doing it sooner keeps
 * every following turn smaller, which is where the saving comes from: the
 * compaction turn itself costs something, so this only pays off on sessions
 * long enough to keep going afterwards.
 */

/** Below this the window is too small for compaction to be worth a turn. */
export const AUTO_COMPACT_MIN_PERCENT = 50;
/** Above this the model's own compaction is imminent anyway. */
export const AUTO_COMPACT_MAX_PERCENT = 90;
export const AUTO_COMPACT_DEFAULT_PERCENT = 70;

export interface AutoCompactInput {
  /** The user's threshold as a percent of the window; null when off. */
  thresholdPercent: number | null;
  /** How full the window is now; null before the first response. */
  percentage: number | null;
  /** A compaction is already under way. */
  isCompacting: boolean;
  /** A turn is in flight, so the session is not at a resting point. */
  isRunning: boolean;
  /**
   * False once this crossing has fired, so a session compacts once per
   * crossing rather than on every render while it sits above the line.
   */
  armed: boolean;
}

export interface AutoCompactDecision {
  compact: boolean;
  armed: boolean;
}

/**
 * Whether to compact now, and whether the next crossing should fire. Firing
 * disarms; dropping back under the threshold re-arms, so a session that keeps
 * growing compacts again later but a failed compaction does not loop.
 */
export function decideAutoCompact({
  thresholdPercent,
  percentage,
  isCompacting,
  isRunning,
  armed,
}: AutoCompactInput): AutoCompactDecision {
  if (thresholdPercent === null || percentage === null) {
    return { compact: false, armed: true };
  }
  if (percentage < thresholdPercent) return { compact: false, armed: true };
  if (!armed || isCompacting || isRunning) return { compact: false, armed };
  return { compact: true, armed: false };
}

/** Keeps a stored threshold inside the range the slider offers. */
export function clampAutoCompactPercent(value: number): number {
  return Math.min(
    AUTO_COMPACT_MAX_PERCENT,
    Math.max(AUTO_COMPACT_MIN_PERCENT, Math.round(value)),
  );
}
