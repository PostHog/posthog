// UI events emitted from main to renderer
export const UIServiceEvent = {
  OpenSettings: "open-settings",
  NewTask: "new-task",
  ResetLayout: "reset-layout",
  ClearStorage: "clear-storage",
  InvalidateToken: "invalidate-token",
} as const;

// UI events are simple signals - payload is just a marker that the event fired
export interface UIServiceEvents {
  [UIServiceEvent.OpenSettings]: true;
  [UIServiceEvent.NewTask]: true;
  [UIServiceEvent.ResetLayout]: true;
  [UIServiceEvent.ClearStorage]: true;
  [UIServiceEvent.InvalidateToken]: true;
}
