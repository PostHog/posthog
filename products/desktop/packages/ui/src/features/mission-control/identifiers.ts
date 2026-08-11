export interface MissionControlState {
  active: boolean;
}

export interface MissionControlClient {
  onStateChanged(onData: (state: MissionControlState) => void): () => void;
}

export const MISSION_CONTROL_CLIENT = Symbol.for(
  "posthog.ui.mission-control.client",
);
