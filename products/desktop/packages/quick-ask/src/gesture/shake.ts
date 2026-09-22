/**
 * Shake gesture over a stream of cursor x positions: enough horizontal
 * direction reversals of a minimum swing, close enough together.
 */

/** A reversal counts only after the cursor swings back this many pixels. */
const SWING_PX = 14;
/** Reversals must all land inside this window. */
const WINDOW_MS = 900;
/** Reversals needed to call it a shake. */
const REVERSALS = 3;

export class ShakeDetector {
  private direction: 1 | -1 | 0 = 0;
  /** Furthest x reached in the current direction. */
  private extremeX = 0;
  private reversalTimes: number[] = [];
  private started = false;

  /** Feed one cursor sample; true when a shake completes (then re-arms). */
  sample(x: number, now: number): boolean {
    if (!this.started) {
      this.started = true;
      this.extremeX = x;
      return false;
    }
    if (this.direction >= 0 && x > this.extremeX) {
      this.direction = 1;
      this.extremeX = x;
      return false;
    }
    if (this.direction <= 0 && x < this.extremeX) {
      this.direction = -1;
      this.extremeX = x;
      return false;
    }
    if (Math.abs(x - this.extremeX) < SWING_PX) {
      return false;
    }
    // Swung back past the threshold: a reversal.
    this.direction = x > this.extremeX ? 1 : -1;
    this.extremeX = x;
    this.reversalTimes = this.reversalTimes.filter(
      (time) => now - time < WINDOW_MS,
    );
    this.reversalTimes.push(now);
    if (this.reversalTimes.length >= REVERSALS) {
      this.reversalTimes = [];
      return true;
    }
    return false;
  }

  reset(): void {
    this.direction = 0;
    this.extremeX = 0;
    this.reversalTimes = [];
    this.started = false;
  }
}
