/**
 * UI-side client for the Mission Control overlay. Detection needs undocumented
 * macOS APIs, so it lives in the host service; this is the host-neutral surface
 * the renderer sees. Hosts that cannot detect it never emit, and the overlay
 * never shows.
 */

export interface MissionControlState {
  active: boolean;
}

export interface MissionControlClient {
  /** Observe enter/exit; returns an unsubscribe function. */
  onStateChanged(onData: (state: MissionControlState) => void): () => void;
}

export const MISSION_CONTROL_CLIENT = Symbol.for(
  "posthog.ui.mission-control.client",
);
