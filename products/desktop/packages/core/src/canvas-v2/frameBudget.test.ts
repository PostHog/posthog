import { describe, expect, it } from "vitest";
import { TokenBucket } from "./frameBudget";

const limit = { burst: 3, perSecond: 1 };

describe("TokenBucket", () => {
  it("spends the burst, then refuses", () => {
    const bucket = new TokenBucket(limit, 0);
    expect([bucket.take(0), bucket.take(0), bucket.take(0)]).toEqual([
      true,
      true,
      true,
    ]);
    expect(bucket.take(0)).toBe(false);
  });

  it("gives the allowance back over time, up to the burst", () => {
    const bucket = new TokenBucket(limit, 0);
    for (let i = 0; i < 3; i += 1) bucket.take(0);
    expect(bucket.take(500)).toBe(false);
    expect(bucket.take(1000)).toBe(true);
    expect(bucket.take(60_000)).toBe(true);
    expect(bucket.take(60_000)).toBe(true);
    expect(bucket.take(60_000)).toBe(true);
    expect(bucket.take(60_000)).toBe(false);
  });

  it("says how long the wait is", () => {
    const bucket = new TokenBucket(limit, 0);
    for (let i = 0; i < 3; i += 1) bucket.take(0);
    expect(bucket.waitSeconds(0)).toBeCloseTo(1, 5);
    expect(bucket.waitSeconds(500)).toBeCloseTo(0.5, 5);
    expect(bucket.waitSeconds(1000)).toBe(0);
  });
});
