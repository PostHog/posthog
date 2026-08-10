/**
 * UI-side client for the Mission Control overlay. Detecting Mission Control
 * needs undocumented macOS APIs, so all of that lives in the host service
 * (`apps/code` main process); this is the thin, host-neutral surface the
 * renderer talks to. Hosts that can't detect it simply never emit, and the
 * overlay never shows.
 */

export interface MissionControlState {
  /** True while the app window is showing inside macOS Mission Control. */
  active: boolean;
}

export interface MissionControlClient {
  getState(): Promise<MissionControlState>;
  /** Observe enter/exit; returns an unsubscribe function. */
  onStateChanged(onData: (state: MissionControlState) => void): () => void;
}

export const MISSION_CONTROL_CLIENT = Symbol.for(
  "posthog.ui.mission-control.client",
);
