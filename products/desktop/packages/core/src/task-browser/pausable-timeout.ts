export class PausableTimeout {
  private remaining: number;
  private startedAt = 0;
  private pauses = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(
    durationMs: number,
    private readonly onTimeout: () => void,
  ) {
    this.remaining = durationMs;
    this.resume();
  }

  pause(): void {
    if (this.stopped) return;
    this.pauses += 1;
    if (this.pauses > 1 || !this.timer) return;
    clearTimeout(this.timer);
    this.timer = null;
    this.remaining = Math.max(
      0,
      this.remaining - (performance.now() - this.startedAt),
    );
  }

  unpause(): void {
    if (this.stopped || this.pauses === 0) return;
    this.pauses -= 1;
    if (this.pauses === 0) this.resume();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private resume(): void {
    this.startedAt = performance.now();
    this.timer = setTimeout(() => {
      this.stopped = true;
      this.onTimeout();
    }, this.remaining);
  }
}
