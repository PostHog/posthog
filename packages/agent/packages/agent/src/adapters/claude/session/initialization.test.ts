import { PassThrough } from "node:stream";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionInitialization } from "./initialization";

function hookEvent(subtype: string, hookId = "example-hook"): string {
  return `${JSON.stringify({
    type: "system",
    subtype,
    hook_event: "SessionStart",
    hook_id: hookId,
  })}\n`;
}

describe("SessionInitialization", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("allows setup to finish after the connection deadline without consuming SDK output", async () => {
    const stdout = new PassThrough();
    const received: string[] = [];
    stdout.on("data", (chunk: Buffer) => received.push(chunk.toString()));
    const monitor = new SessionInitialization(vi.fn());
    monitor.observe(stdout);
    let finish!: (value: string) => void;
    const result = monitor.wait(
      new Promise<string>((resolve) => {
        finish = resolve;
      }),
    );
    const settled = vi.fn();
    void result.then(settled);
    const start = hookEvent("hook_started");
    stdout.write(start.slice(0, 20));
    stdout.write(start.slice(20));

    await vi.advanceTimersByTimeAsync(32_000);
    expect(settled).not.toHaveBeenCalled();

    const complete = hookEvent("hook_response");
    stdout.write(complete);
    finish("ready");
    await expect(result).resolves.toEqual({
      result: "success",
      value: "ready",
    });
    expect(received.join("")).toBe(start + complete);
    expect(stdout.listenerCount("data")).toBe(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(["no hooks", "hooks complete", "hooks still running"] as const)(
    "bounds stalled initialization with %s",
    async (scenario) => {
      const stdout = new PassThrough();
      const monitor = new SessionInitialization(vi.fn());
      monitor.observe(stdout);
      const result = monitor.wait(new Promise<never>(() => {}));
      if (scenario !== "no hooks") stdout.write(hookEvent("hook_started"));
      if (scenario === "hooks complete")
        stdout.write(hookEvent("hook_response"));

      const hooksRunning = scenario === "hooks still running";
      const timeoutMs = hooksRunning ? 600_000 : 30_000;
      await vi.advanceTimersByTimeAsync(timeoutMs - 1);
      stdout.write(hookEvent("hook_progress"));
      await vi.advanceTimersByTimeAsync(1);

      await expect(result).resolves.toEqual({
        result: "timeout",
        phase: hooksRunning ? "setup_hooks" : "sdk_initialization",
        timeoutMs,
        cliOutput: {
          lines: {
            "no hooks": 1,
            "hooks complete": 3,
            "hooks still running": 2,
          }[scenario],
          hasPartialLine: false,
          msSinceLastLine: 1,
          lastMessageType: "system/hook_progress",
        },
      });
      expect(stdout.listenerCount("data")).toBe(0);
    },
  );

  it("reports partial output and bounds message type labels", async () => {
    const stdout = new PassThrough();
    const monitor = new SessionInitialization(vi.fn());
    monitor.observe(stdout);
    const result = monitor.wait(new Promise<never>(() => {}));
    stdout.write(`${JSON.stringify({ type: "x".repeat(150) })}\npartial`);

    await vi.advanceTimersByTimeAsync(30_000);

    await expect(result).resolves.toMatchObject({
      result: "timeout",
      cliOutput: {
        lines: 1,
        hasPartialLine: true,
        msSinceLastLine: 30_000,
        lastMessageType: "x".repeat(100),
      },
    });
  });

  it("waits for all concurrent hooks and ignores oversized unrelated output", async () => {
    const stdout = new PassThrough();
    const monitor = new SessionInitialization(vi.fn());
    monitor.observe(stdout);
    const result = monitor.wait(new Promise<never>(() => {}));
    stdout.write("x".repeat(300_000));
    stdout.write(
      `\n${hookEvent("hook_started", "first")}${hookEvent("hook_started", "second")}`,
    );
    stdout.write(hookEvent("hook_response", "first"));
    await vi.advanceTimersByTimeAsync(32_000);
    expect(monitor.phase).toBe("setup_hooks");
    stdout.write(hookEvent("hook_response", "second"));
    await vi.advanceTimersByTimeAsync(30_000);
    await expect(result).resolves.toMatchObject({
      result: "timeout",
      phase: "sdk_initialization",
    });
  });

  it("removes observers and timers when the SDK rejects initialization", async () => {
    const stdout = new PassThrough();
    const monitor = new SessionInitialization(vi.fn());
    monitor.observe(stdout);

    await expect(
      monitor.wait(Promise.reject(new Error("Example startup failure"))),
    ).rejects.toThrow("Example startup failure");

    expect(stdout.listenerCount("data")).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([
    ["proxy_invalid", "requires_action"],
    ["worktree_unverified", "transient"],
    ["org_verify_failed", "unknown"],
    ["sandbox_required_unavailable", "requires_action"],
    ["provider_not_allowed", "requires_action"],
    ["org_config_required_unavailable", "unknown"],
    ["org_config_refused", "requires_action"],
    ["future_provider_reason", "unknown"],
    [null, "unknown"],
  ])(
    "preserves structured %s through an SDK rejection",
    async (reason, retryability) => {
      const stdout = new PassThrough();
      const monitor = new SessionInitialization(vi.fn());
      monitor.observe(stdout);
      const line = `${JSON.stringify({
        type: "result",
        subtype: "error_during_execution",
        startup_failure_reason: reason,
      })}\n`;
      stdout.write(line.slice(0, 19));
      stdout.write(line.slice(19));

      await expect(
        monitor.wait(Promise.reject(new Error("SDK initialization failed"))),
      ).rejects.toThrow("SDK initialization failed");

      expect(monitor.failure).toEqual({
        provider: "claude",
        phase: "sdk_initialization",
        reason: reason === "future_provider_reason" ? null : reason,
        retryability,
      });
      expect(stdout.listenerCount("data")).toBe(0);
    },
  );

  it.each([
    "proxy_invalid: the proxy setting is invalid\n",
    `${JSON.stringify({ type: "assistant", startup_failure_reason: "proxy_invalid" })}\n`,
    `${JSON.stringify({ type: "result", subtype: "success", startup_failure_reason: "proxy_invalid" })}\n`,
    `${JSON.stringify({ type: "result", subtype: "error_during_execution", errors: ["proxy_invalid"] })}\n`,
  ])("does not classify unrelated output %s", async (output) => {
    const stdout = new PassThrough();
    const monitor = new SessionInitialization(vi.fn());
    monitor.observe(stdout);
    stdout.write(output);
    expect(monitor.failure).toMatchObject({
      reason: null,
      retryability: "unknown",
    });
    await monitor.wait(Promise.resolve());
  });
});
