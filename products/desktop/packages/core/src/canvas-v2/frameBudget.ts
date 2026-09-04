export interface TokenBucketLimit {
  readonly burst: number;
  readonly perSecond: number;
}

export const CANVAS_V2_READ_LIMIT: TokenBucketLimit = {
  burst: 120,
  perSecond: 3,
};

export const CANVAS_V2_WRITE_LIMIT: TokenBucketLimit = {
  burst: 120,
  perSecond: 10,
};

export const CANVAS_V2_MAX_READS_IN_FLIGHT = 8;

export const CANVAS_V2_MAX_READS_WAITING = 200;

export class TokenBucket {
  private tokens: number;
  private updatedAt: number;

  constructor(
    private readonly limit: TokenBucketLimit,
    now: number,
  ) {
    this.tokens = limit.burst;
    this.updatedAt = now;
  }

  take(now: number): boolean {
    this.refill(now);
    if (this.tokens < 1) return false;
    this.tokens -= 1;
    return true;
  }

  waitSeconds(now: number): number {
    this.refill(now);
    if (this.tokens >= 1) return 0;
    return (1 - this.tokens) / this.limit.perSecond;
  }

  private refill(now: number): void {
    const seconds = Math.max(0, (now - this.updatedAt) / 1000);
    this.updatedAt = now;
    this.tokens = Math.min(
      this.limit.burst,
      this.tokens + seconds * this.limit.perSecond,
    );
  }
}
