import { describe, expect, it } from "vitest";
import { ShakeDetector } from "./shake";

/** Feeds a left-right zigzag of the given amplitude; returns first fire time. */
function zigzag(
  detector: ShakeDetector,
  amplitude: number,
  swings: number,
  stepMs = 60,
): number | null {
  let now = 0;
  for (let swing = 0; swing < swings; swing++) {
    const x = swing % 2 === 0 ? amplitude : 0;
    now += stepMs;
    if (detector.sample(x, now)) return now;
  }
  return null;
}

describe("ShakeDetector", () => {
  it("fires after enough fast wide swings and re-arms", () => {
    const detector = new ShakeDetector();
    expect(zigzag(detector, 40, 8)).not.toBeNull();
    // Re-armed: the same gesture fires again.
    detector.reset();
    expect(zigzag(detector, 40, 8)).not.toBeNull();
  });

  it("ignores small jitter", () => {
    const detector = new ShakeDetector();
    expect(zigzag(detector, 8, 40)).toBeNull();
  });

  it("ignores slow back-and-forth", () => {
    const detector = new ShakeDetector();
    expect(zigzag(detector, 40, 20, 600)).toBeNull();
  });

  it("a straight drag never fires", () => {
    const detector = new ShakeDetector();
    for (let i = 0; i < 100; i++) {
      expect(detector.sample(i * 20, i * 15)).toBe(false);
    }
  });
});
