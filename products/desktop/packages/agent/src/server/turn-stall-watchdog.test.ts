import { afterEach, describe, expect, it, vi } from "vitest";
import {
  readTurnStallTimeoutMs,
  TurnStallWatchdog,
  type TurnStallWatchdogOptions,
} from "./turn-stall-watchdog";

describe("TurnStallWatchdog", () => {
  let clock = 0;
  const now = () => clock;

  function createWatchdog(overrides: Partial<TurnStallWatchdogOptions> = {}): {
    watchdog: TurnStallWatchdog;
    probe: ReturnType<typeof vi.fn>;
    onStall: ReturnType<typeof vi.fn>;
  } {
    const probe = vi.fn(async () => true);
    const onStall = vi.fn(async () => {});
    const options: TurnStallWatchdogOptions = {
      softTimeoutMs: 1_000,
      hardTimeoutMs: 5_000,
      checkIntervalMs: 100,
      probe,
      onStall,
      now,
      ...overrides,
    };
    const watchdog = new TurnStallWatchdog(options);
    return {
      watchdog,
      probe: options.probe as ReturnType<typeof vi.fn>,
      onStall: options.onStall as ReturnType<typeof vi.fn>,
    };
  }

  afterEach(() => {
    clock = 0;
    vi.useRealTimers();
  });

  it("ignores a probe result when the adapter produced output while it was pending", async () => {
    let resolveProbe!: (value: boolean) => void;
    const { watchdog, onStall } = createWatchdog({
      probe: vi.fn(
        () =>
          new Promise<boolean>((resolve) => {
            resolveProbe = resolve;
          }),
      ),
    });
    watchdog.start();

    clock = 1_500;
    const tick = watchdog.tick();
    watchdog.recordActivity();
    resolveProbe(false);
    await tick;

    expect(onStall).not.toHaveBeenCalled();
    expect(watchdog.running).toBe(true);
    watchdog.stop();
  });

  it("ignores a probe result when the turn stopped and a new one started while it was pending", async () => {
    let resolveProbe!: (value: boolean) => void;
    const { watchdog, onStall } = createWatchdog({
      probe: vi.fn(
        () =>
          new Promise<boolean>((resolve) => {
            resolveProbe = resolve;
          }),
      ),
    });
    watchdog.start();

    clock = 1_500;
    const tick = watchdog.tick();
    watchdog.stop();
    watchdog.start();
    resolveProbe(false);
    await tick;

    expect(onStall).not.toHaveBeenCalled();
    expect(watchdog.running).toBe(true);
    watchdog.stop();
  });

  it("does nothing while the adapter keeps producing output", async () => {
    const { watchdog, probe, onStall } = createWatchdog();
    watchdog.start();

    clock = 900;
    watchdog.recordActivity();
    clock = 1_800;
    await watchdog.tick();

    expect(probe).not.toHaveBeenCalled();
    expect(onStall).not.toHaveBeenCalled();
    watchdog.stop();
  });

  it("probes after the soft timeout and stalls when the sandbox does not answer", async () => {
    const { watchdog, probe, onStall } = createWatchdog({
      probe: vi.fn(async () => false),
    });
    watchdog.start();

    clock = 1_000;
    await watchdog.tick();

    expect(probe).toHaveBeenCalledOnce();
    expect(onStall).toHaveBeenCalledWith("sandbox_unresponsive", 1_000);
    watchdog.stop();
  });

  it("keeps waiting when the sandbox still answers a quiet turn", async () => {
    const { watchdog, probe, onStall } = createWatchdog();
    watchdog.start();

    clock = 1_000;
    await watchdog.tick();
    clock = 2_000;
    await watchdog.tick();

    expect(probe).toHaveBeenCalledTimes(2);
    expect(onStall).not.toHaveBeenCalled();
    watchdog.stop();
  });

  it("stalls a silent turn at the hard timeout even when the probe passes", async () => {
    const { watchdog, probe, onStall } = createWatchdog();
    watchdog.start();

    clock = 5_000;
    await watchdog.tick();

    expect(probe).not.toHaveBeenCalled();
    expect(onStall).toHaveBeenCalledWith("turn_silent", 5_000);
    watchdog.stop();
  });

  it("treats a turn waiting on a person as active", async () => {
    let waiting = true;
    const { watchdog, probe, onStall } = createWatchdog({
      isWaitingOnUser: () => waiting,
    });
    watchdog.start();

    clock = 6_000;
    await watchdog.tick();
    waiting = false;
    clock = 6_500;
    await watchdog.tick();

    expect(probe).not.toHaveBeenCalled();
    expect(onStall).not.toHaveBeenCalled();
    watchdog.stop();
  });

  it("fires at most once per turn and resets on the next start", async () => {
    const { watchdog, onStall } = createWatchdog({
      probe: vi.fn(async () => false),
    });
    watchdog.start();
    clock = 1_000;
    await watchdog.tick();
    await watchdog.tick();
    expect(onStall).toHaveBeenCalledOnce();

    watchdog.stop();
    watchdog.start();
    clock = 2_000;
    await watchdog.tick();
    expect(onStall).toHaveBeenCalledTimes(2);
    watchdog.stop();
  });

  it("stays off when both timeouts are disabled", () => {
    const { watchdog } = createWatchdog({ softTimeoutMs: 0, hardTimeoutMs: 0 });
    watchdog.start();
    expect(watchdog.enabled).toBe(false);
    expect(watchdog.running).toBe(false);
  });

  it("ticks on the check interval once started", async () => {
    vi.useFakeTimers();
    const { watchdog, onStall } = createWatchdog({
      probe: vi.fn(async () => false),
      now: Date.now,
      softTimeoutMs: 250,
      hardTimeoutMs: 0,
    });
    watchdog.start();

    await vi.advanceTimersByTimeAsync(400);

    expect(onStall).toHaveBeenCalledOnce();
    expect(onStall.mock.calls[0]?.[0]).toBe("sandbox_unresponsive");
    watchdog.stop();
  });

  it.each([
    [undefined, 10, 10],
    ["", 10, 10],
    ["0", 10, 0],
    ["1500", 10, 1500],
    ["nope", 10, 10],
    ["-5", 10, 10],
  ])("readTurnStallTimeoutMs(%j) -> %i", (value, fallback, expected) => {
    expect(readTurnStallTimeoutMs(value, fallback)).toBe(expected);
  });
});
