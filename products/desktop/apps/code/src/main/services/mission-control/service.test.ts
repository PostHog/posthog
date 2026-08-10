import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MissionControlServiceEvent } from "./schemas";
import type { CgWindow, WindowListSampler } from "./window-list";

vi.mock("../../utils/logger", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

const sampler = vi.hoisted(() => ({
  create: vi.fn<() => WindowListSampler | null>(),
}));
vi.mock("./cg-window-list", () => ({
  createWindowListSampler: sampler.create,
}));

import { MissionControlService } from "./service";

const DOCK_AT_MINUS_ONE: CgWindow = {
  ownerName: "Dock",
  layer: 20,
  bounds: { x: 0, y: -1, width: 1440, height: 901 },
};

/** A sampler whose next return value the test controls. */
function fakeSampler(initial: CgWindow[] = []) {
  const state = { windows: initial, error: null as Error | null };
  const impl: WindowListSampler = {
    sample: () => {
      if (state.error) throw state.error;
      return state.windows;
    },
  };
  return { state, impl };
}

/** MissionControlService is macOS-only; pretend we're there unless told not to. */
function pretendPlatform(platform: string) {
  Object.defineProperty(process, "platform", {
    value: platform,
    configurable: true,
  });
}

const realPlatform = process.platform;

describe("MissionControlService", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    sampler.create.mockReset();
    pretendPlatform("darwin");
  });

  afterEach(() => {
    vi.useRealTimers();
    pretendPlatform(realPlatform);
  });

  it("emits once when Mission Control opens and once when it closes", () => {
    const { state, impl } = fakeSampler();
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();
    const seen: boolean[] = [];
    service.on(MissionControlServiceEvent.StateChanged, ({ active }) =>
      seen.push(active),
    );

    service.arm();
    vi.advanceTimersByTime(1000);
    expect(seen).toEqual([]);

    state.windows = [DOCK_AT_MINUS_ONE];
    vi.advanceTimersByTime(1000);

    state.windows = [];
    vi.advanceTimersByTime(1000);

    // Four ticks per state, one event per transition.
    expect(seen).toEqual([true, false]);
  });

  it("stops polling once disarmed, and drops the overlay", () => {
    const { state, impl } = fakeSampler([DOCK_AT_MINUS_ONE]);
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    vi.advanceTimersByTime(250);
    expect(service.getState().active).toBe(true);

    service.disarm();
    expect(service.getState().active).toBe(false);

    // Mission Control is still "open", but nothing is watching any more.
    state.windows = [DOCK_AT_MINUS_ONE];
    vi.advanceTimersByTime(5000);
    expect(service.getState().active).toBe(false);
  });

  it("gives up after repeated sampling failures instead of logging forever", () => {
    const { state, impl } = fakeSampler();
    const sampleSpy = vi.spyOn(impl, "sample");
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    state.error = new Error("CoreGraphics went away");
    vi.advanceTimersByTime(250 * 10);

    expect(sampleSpy).toHaveBeenCalledTimes(3);
  });

  it("never touches the window list off macOS", () => {
    pretendPlatform("linux");
    const service = new MissionControlService();

    service.arm();
    vi.advanceTimersByTime(5000);

    expect(sampler.create).not.toHaveBeenCalled();
    expect(service.getState().active).toBe(false);
  });

  it("degrades quietly when the window list is unavailable", () => {
    sampler.create.mockReturnValue(null);
    const service = new MissionControlService();

    service.arm();
    vi.advanceTimersByTime(5000);

    // Resolved once, then never retried.
    expect(sampler.create).toHaveBeenCalledTimes(1);
    expect(service.getState().active).toBe(false);
  });

  it("forces the overlay on without any detection at all", () => {
    pretendPlatform("linux");
    const service = new MissionControlService();
    const seen: boolean[] = [];
    service.on(MissionControlServiceEvent.StateChanged, ({ active }) =>
      seen.push(active),
    );

    expect(service.setForced(true)).toEqual({ active: true });
    expect(service.setForced(false)).toEqual({ active: false });
    expect(seen).toEqual([true, false]);
  });

  it("keeps a forced overlay up across polls that see nothing", () => {
    const { impl } = fakeSampler();
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    service.setForced(true);
    vi.advanceTimersByTime(1000);

    expect(service.getState().active).toBe(true);
  });
});
