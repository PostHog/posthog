import { setTimeout as delay } from "node:timers/promises";
import { TypedEventEmitter } from "@posthog/shared";
import { screen } from "electron";
import { injectable, preDestroy } from "inversify";
import { createWindowListSampler } from "../services/mission-control/cg-window-list";
import {
  detectMissionControl,
  windowKey,
} from "../services/mission-control/heuristic";
import {
  type MissionControlProbe,
  MissionControlServiceEvent,
  type MissionControlServiceEvents,
  type MissionControlState,
} from "../services/mission-control/schemas";
import type {
  CgWindow,
  Rect,
  WindowListSampler,
} from "../services/mission-control/window-list";
import { logger } from "../utils/logger";

const log = logger.scope("mission-control");

/**
 * Mission Control's zoom-out animation runs about 300ms, so a shorter interval
 * buys nothing a user can perceive while a longer one lands the overlay after
 * the grid has settled.
 */
const POLL_INTERVAL_MS = 250;

/** Give up rather than log a failing CoreGraphics call four times a second. */
const MAX_CONSECUTIVE_ERRORS = 3;

/**
 * Detects when the app window is showing inside macOS Mission Control, so the
 * renderer can put up a big branded overlay and make the window easy to pick
 * out of a grid of near-identical dark windows.
 *
 * Everything here is best-effort by construction: the detection relies on
 * undocumented Dock window geometry reached through FFI. Any failure — wrong
 * platform, missing prebuild, changed macOS internals — degrades to "the
 * overlay never appears", never to a broken app.
 */
@injectable()
export class MissionControlService extends TypedEventEmitter<MissionControlServiceEvents> {
  /** Null until armed, and permanently null once detection is unavailable. */
  private sampler: WindowListSampler | null = null;
  private samplerResolved = false;
  private degraded = process.platform !== "darwin";
  private timer: NodeJS.Timeout | null = null;
  private active = false;
  private forced = false;
  private consecutiveErrors = 0;

  getState(): MissionControlState {
    return { active: this.active };
  }

  /**
   * Start watching. Called when the window becomes visible — there is no point
   * polling while the app is hidden or minimized, since it can't appear in
   * Mission Control either way.
   */
  arm(): void {
    if (this.timer) return;
    if (!this.resolveSampler()) return;

    // Logged on success, not only on failure. Detection going quiet looks
    // identical to the poller never starting, and the dev toolbar only installs
    // log capture when developer mode goes on — after boot — so a line emitted
    // once at startup is one nobody ever reads.
    log.info("Watching for Mission Control", { intervalMs: POLL_INTERVAL_MS });
    this.timer = setInterval(() => this.poll(), POLL_INTERVAL_MS);
  }

  /** Stop watching and drop any overlay that was up. */
  disarm(): void {
    this.clearTimer();
    this.setActive(false);
  }

  /**
   * Dev-only override that pins the overlay on, so the visuals can be reviewed
   * without a Mac and without opening Mission Control.
   */
  setForced(forced: boolean): MissionControlState {
    this.forced = forced;
    if (forced) {
      this.setActive(true);
    } else {
      // Let the next poll decide; if we aren't polling, fall back to hidden.
      this.setActive(false);
    }
    return this.getState();
  }

  /**
   * Watch the window list for `durationMs` and report what changed, so the
   * heuristic can be checked on a real Mac: start this, open Mission Control,
   * and read which window appeared.
   *
   * A one-shot dump cannot do this job. Mission Control is a modal system
   * overlay, so the app is unclickable for as long as it is up — a sample taken
   * when you press the button is always a sample of the ordinary desktop.
   */
  async probe(durationMs: number): Promise<MissionControlProbe> {
    const sampler = this.resolveSampler();
    const empty = {
      durationMs,
      detected: false,
      appeared: [],
      disappeared: [],
      baselineCount: 0,
    };
    if (!sampler) return { available: false, ...empty };

    try {
      const baseline = sampler.sample();
      const baselineByKey = new Map(
        baseline.map((window) => [windowKey(window), window]),
      );
      const appeared = new Map<string, CgWindow>();
      // Baseline windows seen in every sample so far. A window that vanishes
      // even once drops out and is reported as disappeared.
      const survived = new Set(baselineByKey.keys());
      let detected = false;

      const deadline = Date.now() + durationMs;
      while (Date.now() < deadline) {
        await delay(POLL_INTERVAL_MS);
        const current = sampler.sample();
        if (detectMissionControl(current, this.displayBounds()))
          detected = true;

        const currentKeys = new Set(current.map(windowKey));
        for (const window of current) {
          const key = windowKey(window);
          if (!baselineByKey.has(key)) appeared.set(key, window);
        }
        for (const key of survived) {
          if (!currentKeys.has(key)) survived.delete(key);
        }
      }

      const result: MissionControlProbe = {
        available: true,
        durationMs,
        detected,
        appeared: [...appeared.values()],
        disappeared: [...baselineByKey]
          .filter(([key]) => !survived.has(key))
          .map(([, window]) => window),
        baselineCount: baseline.length,
      };
      // Logged here rather than from the renderer, where it was raised: renderer
      // lines do not reach the dev toolbar's log panel, and this is the one
      // artifact worth keeping a durable copy of.
      log.info("Probe finished", {
        detected: result.detected,
        appeared: result.appeared.length,
        displays: this.displayBounds(),
      });
      return result;
    } catch (error) {
      log.warn("Failed to read the window list", { error });
      return { available: false, ...empty };
    }
  }

  @preDestroy()
  cleanup(): void {
    this.clearTimer();
  }

  /**
   * The sampler, created on first use. Null means detection is unavailable and
   * will stay that way: a wrong platform or a failed dlopen does not get better
   * on a retry, so resolve it once and remember.
   */
  private resolveSampler(): WindowListSampler | null {
    if (this.degraded) return null;
    if (this.samplerResolved) return this.sampler;

    this.samplerResolved = true;
    try {
      this.sampler = createWindowListSampler();
    } catch (error) {
      // Almost always a missing @koromix/koffi-darwin-* prebuild or a dlopen the
      // hardened runtime refused. Both are silent in every other symptom, so the
      // reason is the whole value of this line.
      log.warn("Could not bind the CoreGraphics window list", { error });
      this.sampler = null;
    }

    if (!this.sampler) {
      this.degraded = true;
      log.info("Mission Control overlay disabled", {
        platform: process.platform,
      });
    }
    return this.sampler;
  }

  /**
   * Display bounds for the coverage test, read per sample rather than cached so
   * plugging in a monitor or changing resolution needs no invalidation. It is an
   * in-process lookup, cheap at this interval.
   */
  private displayBounds(): Rect[] {
    return screen.getAllDisplays().map((display) => display.bounds);
  }

  private poll(): void {
    if (!this.sampler) return;

    let detected: boolean;
    try {
      detected = detectMissionControl(
        this.sampler.sample(),
        this.displayBounds(),
      );
      this.consecutiveErrors = 0;
    } catch (error) {
      this.consecutiveErrors += 1;
      if (this.consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
        log.warn("Giving up on Mission Control detection", { error });
        this.degraded = true;
        this.disarm();
      }
      return;
    }

    this.setActive(detected || this.forced);
  }

  private setActive(active: boolean): void {
    if (active === this.active) return;
    this.active = active;
    // One line per transition, not per tick — enough to tell "detection never
    // fires" from "the renderer never draws it" when the overlay misbehaves.
    log.info("Overlay state changed", { active });
    this.emit(MissionControlServiceEvent.StateChanged, this.getState());
  }

  private clearTimer(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
