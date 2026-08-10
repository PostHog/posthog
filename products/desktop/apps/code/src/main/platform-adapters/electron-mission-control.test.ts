import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MissionControlServiceEvent } from "../services/mission-control/schemas";
import type {
  CgWindow,
  WindowListSampler,
} from "../services/mission-control/window-list";

vi.mock("../utils/logger", () => ({
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
vi.mock("../services/mission-control/cg-window-list", () => ({
  createWindowListSampler: sampler.create,
}));

// One 2560x1440 display, so the full-display coverage test has something to
// match against.
vi.mock("electron", () => ({
  screen: {
    getAllDisplays: () => [
      { bounds: { x: 0, y: 0, width: 2560, height: 1440 } },
    ],
  },
}));

import { MissionControlService } from "./electron-mission-control";

/** The full-display Dock window Mission Control puts up. */
const MISSION_CONTROL_BACKING: CgWindow = {
  ownerName: "Dock",
  ownerPid: 300,
  layer: 20,
  bounds: { x: 0, y: 0, width: 2560, height: 1440 },
};

/** The Dock's own strip, present with or without Mission Control. */
const DOCK_STRIP: CgWindow = {
  ownerName: "Dock",
  ownerPid: 300,
  layer: 20,
  bounds: { x: 1030, y: 1330, width: 500, height: 110 },
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

    state.windows = [MISSION_CONTROL_BACKING];
    vi.advanceTimersByTime(1000);

    state.windows = [];
    vi.advanceTimersByTime(1000);

    // Four ticks per state, one event per transition.
    expect(seen).toEqual([true, false]);
  });

  it("stops polling once disarmed, and drops the overlay", () => {
    const { state, impl } = fakeSampler([MISSION_CONTROL_BACKING]);
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    vi.advanceTimersByTime(250);
    expect(service.getState().active).toBe(true);

    service.disarm();
    expect(service.getState().active).toBe(false);

    // Mission Control is still "open", but nothing is watching any more.
    state.windows = [MISSION_CONTROL_BACKING];
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

  it("survives a window list that fails to bind", () => {
    // arm() runs from a BrowserWindow event handler, so a throw here would take
    // the main process down over an easter egg.
    sampler.create.mockImplementation(() => {
      throw new Error("dlopen refused");
    });
    const service = new MissionControlService();

    expect(() => service.arm()).not.toThrow();
    vi.advanceTimersByTime(5000);
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

  it("reports the window that appeared mid-recording, and when", async () => {
    // The whole point of recording rather than sampling on demand: Mission
    // Control is only ever open while the app is unclickable, so the window that
    // identifies it can only be caught by a probe that is already running.
    const { state, impl } = fakeSampler([DOCK_STRIP]);
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    const probe = service.probe(2000);
    // Ordinary desktop for the first stretch, then Mission Control opens.
    await vi.advanceTimersByTimeAsync(500);
    state.windows = [DOCK_STRIP, MISSION_CONTROL_BACKING];
    await vi.advanceTimersByTimeAsync(2000);

    const result = await probe;
    expect(result).toMatchObject({ available: true, baselineCount: 1 });
    expect(result.appeared).toHaveLength(1);

    // Timings are what let one recording cover several gestures, so the window
    // must be stamped with when it showed up, not with the recording's start.
    const [seen] = result.appeared;
    expect(seen).toMatchObject(MISSION_CONTROL_BACKING);
    expect(seen.firstSeenMs).toBeGreaterThan(0);
    expect(seen.lastSeenMs).toBeGreaterThanOrEqual(seen.firstSeenMs);

    // Detection tracks the same window, so it cannot have fired before it.
    expect(result.detectedAtMs.length).toBeGreaterThan(0);
    expect(Math.min(...result.detectedAtMs)).toBe(seen.firstSeenMs);
  });

  it("reports unavailable rather than throwing when there is no window list", async () => {
    pretendPlatform("linux");
    const service = new MissionControlService();

    await expect(service.probe(1000)).resolves.toMatchObject({
      available: false,
      detectedAtMs: [],
      appeared: [],
    });
  });
});
