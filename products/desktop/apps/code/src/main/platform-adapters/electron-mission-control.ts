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
  type ObservedWindow,
} from "../services/mission-control/schemas";
import type {
  Rect,
  WindowListSampler,
} from "../services/mission-control/window-list";
import { logger } from "../utils/logger";

const log = logger.scope("mission-control");

/**
 * Mission Control's zoom animation runs about 300ms, so a shorter interval buys
 * nothing a user can perceive while a longer one lands the overlay after the grid
 * has settled.
 */
const POLL_INTERVAL_MS = 250;

/** Give up rather than log a failing CoreGraphics call four times a second. */
const MAX_CONSECUTIVE_ERRORS = 3;

/**
 * Detects when the app window is showing inside macOS Mission Control, so the
 * renderer can put up a branded overlay and make the window easy to pick out of a
 * grid of near-identical dark windows.
 *
 * Best-effort by construction, since detection rests on undocumented Dock window
 * geometry reached through FFI. Every failure — wrong platform, missing prebuild,
 * changed macOS internals — degrades to "the overlay never appears".
 */
@injectable()
export class MissionControlService extends TypedEventEmitter<MissionControlServiceEvents> {
  /**
   * Resolved once. A wrong platform or a refused dlopen does not get better on a
   * retry, so null after `resolved` means detection is off for this run.
   */
  private sampler: WindowListSampler | null = null;
  private resolved = false;
  private timer: NodeJS.Timeout | null = null;
  private active = false;
  private forced = false;
  private consecutiveErrors = 0;

  getState(): MissionControlState {
    return { active: this.active };
  }

  /**
   * Called when the window becomes visible. A hidden or minimized window cannot
   * appear in Mission Control, so polling then would be waste.
   */
  arm(): void {
    if (this.timer || !this.resolveSampler()) return;
    this.timer = setInterval(() => this.poll(), POLL_INTERVAL_MS);
  }

  disarm(): void {
    this.clearTimer();
    this.setActive(false);
  }

  /** Dev-only: pin the overlay on to review it without opening Mission Control. */
  setForced(forced: boolean): MissionControlState {
    this.forced = forced;
    this.setActive(forced);
    return this.getState();
  }

  /**
   * Record what the window list does for `durationMs`, to re-derive the detection
   * heuristic when a macOS release breaks it. Start it, run the gestures, and read
   * which windows appeared and when.
   */
  async probe(durationMs: number): Promise<MissionControlProbe> {
    const sampler = this.resolveSampler();
    if (!sampler) {
      return { available: false, durationMs, detectedAtMs: [], appeared: [] };
    }

    try {
      const startedAt = Date.now();
      const baseline = new Set(sampler.sample().map(windowKey));
      const appeared = new Map<string, ObservedWindow>();
      const detectedAtMs: number[] = [];

      while (Date.now() - startedAt < durationMs) {
        await delay(POLL_INTERVAL_MS);
        const at = Date.now() - startedAt;
        const windows = sampler.sample();
        if (detectMissionControl(windows, this.displayBounds())) {
          detectedAtMs.push(at);
        }

        for (const window of windows) {
          const key = windowKey(window);
          if (baseline.has(key)) continue;
          const seen = appeared.get(key);
          if (seen) seen.lastSeenMs = at;
          else
            appeared.set(key, { ...window, firstSeenMs: at, lastSeenMs: at });
        }
      }

      const result: MissionControlProbe = {
        available: true,
        durationMs,
        detectedAtMs,
        appeared: [...appeared.values()].sort(
          (a, b) => a.firstSeenMs - b.firstSeenMs,
        ),
      };
      // The clipboard copy is the intended way to read this, but it can fail
      // silently, and renderer log lines never reach the dev toolbar's panel.
      log.info("Probe finished", { ...result, displays: this.displayBounds() });
      return result;
    } catch (error) {
      log.warn("Failed to read the window list", { error });
      return { available: false, durationMs, detectedAtMs: [], appeared: [] };
    }
  }

  @preDestroy()
  cleanup(): void {
    this.clearTimer();
  }

  private resolveSampler(): WindowListSampler | null {
    if (this.resolved) return this.sampler;
    this.resolved = true;
    // Checked here so the FFI module is never even reached off macOS.
    if (process.platform !== "darwin") return null;

    try {
      this.sampler = createWindowListSampler();
    } catch (error) {
      // Almost always a missing @koromix/koffi-darwin-* prebuild or a dlopen the
      // hardened runtime refused, neither of which has any other symptom.
      log.warn("Could not bind the CoreGraphics window list", { error });
    }
    return this.sampler;
  }

  /** Read per sample, so attaching a monitor needs no invalidation. */
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
        this.sampler = null;
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
