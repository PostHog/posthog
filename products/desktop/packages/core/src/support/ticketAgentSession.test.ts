import { describe, expect, it } from "vitest";
import {
  type TicketAgentThreadState,
  ticketAgentThreadNeverStarted,
} from "./ticketAgentSession";

const HEALTHY: TicketAgentThreadState = {
  workspaceLoaded: true,
  hasRun: false,
  hasWorkspace: false,
  hasSession: false,
};

describe("ticketAgentThreadNeverStarted", () => {
  it.each<[string, Partial<TicketAgentThreadState>]>([
    ["a cloud run exists", { hasRun: true }],
    ["a local workspace exists", { hasWorkspace: true }],
    ["a session is connected", { hasSession: true }],
    ["the workspace list has not loaded", { workspaceLoaded: false }],
  ])("holds off while %s", (_case, overrides) => {
    expect(ticketAgentThreadNeverStarted({ ...HEALTHY, ...overrides })).toBe(
      false,
    );
  });

  it("reports a task that has nothing to connect to", () => {
    expect(ticketAgentThreadNeverStarted(HEALTHY)).toBe(true);
  });
});
