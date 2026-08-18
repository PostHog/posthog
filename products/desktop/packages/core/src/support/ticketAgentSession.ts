export interface TicketAgentThreadState {
  workspaceLoaded: boolean;
  hasRun: boolean;
  hasWorkspace: boolean;
  hasSession: boolean;
}

// A task with no run, no workspace and no live session has nothing to connect
// to. The session reconciler skips it, so the session view would sit on its
// initializing spinner forever with no way back.
export function ticketAgentThreadNeverStarted({
  workspaceLoaded,
  hasRun,
  hasWorkspace,
  hasSession,
}: TicketAgentThreadState): boolean {
  return workspaceLoaded && !hasRun && !hasWorkspace && !hasSession;
}
