import type { IPowerManager } from "@posthog/platform/power-manager";
import type { IWorkspaceSettings } from "@posthog/platform/workspace-settings";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SleepService } from "./sleep";

function makeLogger() {
  const scoped = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };
  return { ...scoped, scope: vi.fn(() => scoped) };
}

function createDeps(preventSleepInitially = true) {
  const release = vi.fn();
  const powerManager: IPowerManager = {
    onResume: vi.fn(() => () => {}),
    preventSleep: vi.fn(() => release),
    hasBuiltInBattery: vi.fn(async () => false),
  };

  let stored = preventSleepInitially;
  const settings: IWorkspaceSettings = {
    getPreventSleepWhileRunning: vi.fn(() => stored),
    setPreventSleepWhileRunning: vi.fn((value: boolean) => {
      stored = value;
    }),
  } as unknown as IWorkspaceSettings;

  const service = new SleepService(powerManager, settings, makeLogger());

  return { service, powerManager, settings, release };
}

describe("SleepService", () => {
  let ctx: ReturnType<typeof createDeps>;

  beforeEach(() => {
    ctx = createDeps(true);
  });

  it("seeds the enabled flag from persisted settings", () => {
    expect(ctx.service.getEnabled()).toBe(true);
    expect(createDeps(false).service.getEnabled()).toBe(false);
  });

  it("does not block sleep when enabled but no activity is active", () => {
    expect(ctx.powerManager.preventSleep).not.toHaveBeenCalled();
  });

  it("blocks sleep once an activity is acquired while enabled", () => {
    ctx.service.acquire("turn-1");
    expect(ctx.powerManager.preventSleep).toHaveBeenCalledTimes(1);
  });

  it("does not block sleep on acquire when disabled", () => {
    const disabled = createDeps(false);
    disabled.service.acquire("turn-1");
    expect(disabled.powerManager.preventSleep).not.toHaveBeenCalled();
  });

  it("acquires the blocker only once across multiple activities", () => {
    ctx.service.acquire("turn-1");
    ctx.service.acquire("turn-2");
    expect(ctx.powerManager.preventSleep).toHaveBeenCalledTimes(1);
  });

  it("keeps blocking until the last activity is released", () => {
    ctx.service.acquire("turn-1");
    ctx.service.acquire("turn-2");

    ctx.service.release("turn-1");
    expect(ctx.release).not.toHaveBeenCalled();

    ctx.service.release("turn-2");
    expect(ctx.release).toHaveBeenCalledTimes(1);
  });

  it("treats releasing an unknown activity as a no-op", () => {
    ctx.service.release("never-acquired");
    expect(ctx.powerManager.preventSleep).not.toHaveBeenCalled();
    expect(ctx.release).not.toHaveBeenCalled();
  });

  it("releases the active blocker and persists when disabled at runtime", () => {
    ctx.service.acquire("turn-1");

    ctx.service.setEnabled(false);

    expect(ctx.service.getEnabled()).toBe(false);
    expect(ctx.settings.setPreventSleepWhileRunning).toHaveBeenCalledWith(
      false,
    );
    expect(ctx.release).toHaveBeenCalledTimes(1);
  });

  it("starts blocking when re-enabled while an activity is still active", () => {
    const disabled = createDeps(false);
    disabled.service.acquire("turn-1");
    expect(disabled.powerManager.preventSleep).not.toHaveBeenCalled();

    disabled.service.setEnabled(true);

    expect(disabled.settings.setPreventSleepWhileRunning).toHaveBeenCalledWith(
      true,
    );
    expect(disabled.powerManager.preventSleep).toHaveBeenCalledTimes(1);
  });

  it("releases the blocker on cleanup", () => {
    ctx.service.acquire("turn-1");
    ctx.service.cleanup();
    expect(ctx.release).toHaveBeenCalledTimes(1);
  });
});
