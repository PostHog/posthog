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

const settings = vi.hoisted(() => ({
  enabled: true,
  set: vi.fn<(value: boolean) => void>(),
}));
vi.mock("../services/settingsStore", () => ({
  getMissionControlOverlayEnabled: () => settings.enabled,
  setMissionControlOverlayEnabled: settings.set,
}));

vi.mock("electron", () => ({
  screen: {
    getAllDisplays: () => [
      { bounds: { x: 0, y: 0, width: 2560, height: 1440 } },
    ],
  },
}));

import { MissionControlService } from "./electron-mission-control";

const MISSION_CONTROL_BACKING: CgWindow = {
  ownerName: "Dock",
  layer: 18,
  bounds: { x: 0, y: 0, width: 2560, height: 1440 },
};

const DOCK_STRIP: CgWindow = {
  ownerName: "Dock",
  layer: 20,
  bounds: { x: 1030, y: 1330, width: 500, height: 110 },
};

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
    settings.enabled = true;
    settings.set.mockReset();
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

    state.windows = [MISSION_CONTROL_BACKING];
    vi.advanceTimersByTime(5000);
    expect(service.getState().active).toBe(false);
  });

  it("never touches the window list while the setting is off", () => {
    settings.enabled = false;
    const { state, impl } = fakeSampler([MISSION_CONTROL_BACKING]);
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    state.windows = [MISSION_CONTROL_BACKING];
    vi.advanceTimersByTime(5000);

    expect(sampler.create).not.toHaveBeenCalled();
    expect(service.getState().active).toBe(false);
  });

  it("turning the setting off drops a live overlay, then back on resumes it", () => {
    const { state, impl } = fakeSampler([MISSION_CONTROL_BACKING]);
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    vi.advanceTimersByTime(250);
    expect(service.getState().active).toBe(true);

    service.setEnabled(false);
    expect(service.getState().active).toBe(false);
    expect(settings.set).toHaveBeenLastCalledWith(false);

    state.windows = [MISSION_CONTROL_BACKING];
    vi.advanceTimersByTime(5000);
    expect(service.getState().active).toBe(false);

    service.setEnabled(true);
    vi.advanceTimersByTime(250);
    expect(settings.set).toHaveBeenLastCalledWith(true);
    expect(service.getState().active).toBe(true);
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

  it("arms once even when show and restore both fire", () => {
    // The window wires both events to arm(); a second interval would double
    // every FFI call.
    const { impl } = fakeSampler();
    const sampleSpy = vi.spyOn(impl, "sample");
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    service.arm();
    vi.advanceTimersByTime(250);

    expect(sampleSpy).toHaveBeenCalledTimes(1);
  });

  it("only counts consecutive failures toward giving up", () => {
    const { state, impl } = fakeSampler();
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    state.error = new Error("flake");
    vi.advanceTimersByTime(500);
    state.error = null;
    vi.advanceTimersByTime(250);
    state.error = new Error("flake");
    vi.advanceTimersByTime(500);

    // Four failures total but never three in a row, so detection still runs.
    state.error = null;
    state.windows = [MISSION_CONTROL_BACKING];
    vi.advanceTimersByTime(250);
    expect(service.getState().active).toBe(true);
  });

  it("retries the window list on a fresh arm after a runtime give-up", () => {
    const { state, impl } = fakeSampler();
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    service.arm();
    state.error = new Error("CoreGraphics went away");
    vi.advanceTimersByTime(250 * 3);

    // Given up: nothing polls even though Mission Control is now detectable.
    state.error = null;
    state.windows = [MISSION_CONTROL_BACKING];
    vi.advanceTimersByTime(1000);
    expect(service.getState().active).toBe(false);

    service.arm();
    vi.advanceTimersByTime(250);

    expect(sampler.create).toHaveBeenCalledTimes(2);
    expect(service.getState().active).toBe(true);
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

    expect(sampler.create).toHaveBeenCalledTimes(1);
    expect(service.getState().active).toBe(false);

    // Unlike a runtime give-up, a failed resolve is final: re-arming must not
    // retry the bind on every window show.
    service.disarm();
    service.arm();
    expect(sampler.create).toHaveBeenCalledTimes(1);
  });

  it("survives a window list that fails to bind", () => {
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
    const { state, impl } = fakeSampler([DOCK_STRIP]);
    sampler.create.mockReturnValue(impl);
    const service = new MissionControlService();

    const probe = service.probe(2000);
    await vi.advanceTimersByTimeAsync(500);
    state.windows = [DOCK_STRIP, MISSION_CONTROL_BACKING];
    await vi.advanceTimersByTimeAsync(2000);

    const result = await probe;
    expect(result).toMatchObject({ available: true });
    expect(result.appeared).toHaveLength(1);

    const [seen] = result.appeared;
    expect(seen).toMatchObject(MISSION_CONTROL_BACKING);
    expect(seen.firstSeenMs).toBeGreaterThan(0);
    expect(seen.lastSeenMs).toBeGreaterThanOrEqual(seen.firstSeenMs);

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
