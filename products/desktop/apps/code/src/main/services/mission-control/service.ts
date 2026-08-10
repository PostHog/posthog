import { TypedEventEmitter } from "@posthog/shared";
import { injectable, preDestroy } from "inversify";
import { logger } from "../../utils/logger";
import { createWindowListSampler } from "./cg-window-list";
import { describeDockWindows, detectMissionControl } from "./heuristic";
import {
  type DockWindowDump,
  MissionControlServiceEvent,
  type MissionControlServiceEvents,
  type MissionControlState,
} from "./schemas";
import type { WindowListSampler } from "./window-list";

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
    if (this.degraded || this.timer) return;

    if (!this.samplerResolved) {
      this.samplerResolved = true;
      this.sampler = createWindowListSampler();
      if (!this.sampler) {
        this.degraded = true;
        log.info(
          "CoreGraphics window list unavailable; Mission Control overlay disabled",
        );
        return;
      }
    }

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

  /** Dock-owned windows in the current sample, for validating the heuristic. */
  debugDump(): DockWindowDump {
    if (!this.samplerResolved) {
      this.samplerResolved = true;
      this.sampler = this.degraded ? null : createWindowListSampler();
      if (!this.sampler) this.degraded = true;
    }

    if (!this.sampler) {
      return { available: false, detected: false, windows: [] };
    }

    try {
      return { available: true, ...describeDockWindows(this.sampler.sample()) };
    } catch (error) {
      log.warn("Failed to read the window list", { error });
      return { available: false, detected: false, windows: [] };
    }
  }

  @preDestroy()
  cleanup(): void {
    this.clearTimer();
  }

  private poll(): void {
    if (!this.sampler) return;

    let detected: boolean;
    try {
      detected = detectMissionControl(this.sampler.sample());
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
    this.emit(MissionControlServiceEvent.StateChanged, this.getState());
  }

  private clearTimer(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
