export interface MissionControlState {
  active: boolean;
}

export interface MissionControlClient {
  onStateChanged(onData: (state: MissionControlState) => void): () => void;
  isSupported(): Promise<boolean>;
  getEnabled(): Promise<boolean>;
  setEnabled(enabled: boolean): Promise<void>;
}

export const MISSION_CONTROL_CLIENT = Symbol.for(
  "posthog.ui.mission-control.client",
);
