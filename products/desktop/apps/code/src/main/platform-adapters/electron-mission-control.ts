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
import {
  getMissionControlOverlayEnabled,
  setMissionControlOverlayEnabled,
} from "../services/settingsStore";
import { logger } from "../utils/logger";

const log = logger.scope("mission-control");

// Mission Control's zoom animation runs about 300ms; polling faster gains
// nothing a user can perceive.
const POLL_INTERVAL_MS = 250;

// Give up rather than log a failing CoreGraphics call four times a second.
const MAX_CONSECUTIVE_ERRORS = 3;

// Best-effort by design: detection rests on undocumented Dock window geometry
// reached through FFI, and every failure degrades to the overlay never showing.
@injectable()
export class MissionControlService extends TypedEventEmitter<MissionControlServiceEvents> {
  private sampler: WindowListSampler | null = null;
  private resolved = false;
  private timer: NodeJS.Timeout | null = null;
  private active = false;
  private forced = false;
  private consecutiveErrors = 0;
  private enabled = getMissionControlOverlayEnabled();

  getState(): MissionControlState {
    return { active: this.active };
  }

  // Only macOS has Mission Control, and the overlay is the only thing the
  // detection drives, so elsewhere the setting has nothing to control.
  isSupported(): boolean {
    return process.platform === "darwin";
  }

  getEnabled(): boolean {
    return this.enabled;
  }

  setEnabled(enabled: boolean): void {
    if (enabled === this.enabled) return;
    this.enabled = enabled;
    setMissionControlOverlayEnabled(enabled);
    // The user turns this on or off from a visible settings window, so arming
    // here matches the window state without waiting for the next show event.
    if (enabled) this.arm();
    else this.disarm();
  }

  arm(): void {
    if (!this.enabled) return;
    if (this.timer || !this.resolveSampler()) return;
    this.timer = setInterval(() => this.poll(), POLL_INTERVAL_MS);
  }

  disarm(): void {
    this.clearTimer();
    this.setActive(false);
  }

  // Dev-only: pins the overlay on without opening Mission Control.
  setForced(forced: boolean): MissionControlState {
    this.forced = forced;
    this.setActive(forced);
    return this.getState();
  }

  // Records the window list so the detection heuristic can be re-derived when
  // a macOS release breaks it.
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
      // Logged as well because the clipboard copy can fail silently.
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
    if (process.platform !== "darwin") return null;

    try {
      this.sampler = createWindowListSampler();
    } catch (error) {
      // Usually a missing @koromix/koffi-darwin-* prebuild or a dlopen the
      // hardened runtime refused, neither of which has any other symptom.
      log.warn("Could not bind the CoreGraphics window list", { error });
    }
    return this.sampler;
  }

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
        // Runtime failures can be transient, so the next arm() re-resolves the
        // sampler; only a failed bind stays off for the rest of the run.
        this.sampler = null;
        this.resolved = false;
        this.consecutiveErrors = 0;
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
