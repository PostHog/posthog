import { describe, expect, it } from "vitest";
import { type AutoRefreshState, shouldAutoRefreshTools } from "./toolRefresh";

function state(overrides: Partial<AutoRefreshState> = {}): AutoRefreshState {
  return {
    autoRefreshIfEmpty: true,
    installationId: "inst-1",
    isLoading: false,
    toolsLength: 0,
    alreadyRefreshed: false,
    refreshPending: false,
    ...overrides,
  };
}

describe("shouldAutoRefreshTools", () => {
  it("fires for an empty, settled, opt-in installation", () => {
    expect(shouldAutoRefreshTools(state())).toBe(true);
  });

  it("does not fire when the opt-in flag is off", () => {
    expect(shouldAutoRefreshTools(state({ autoRefreshIfEmpty: false }))).toBe(
      false,
    );
  });

  it("does not fire without an installation", () => {
    expect(shouldAutoRefreshTools(state({ installationId: null }))).toBe(false);
  });

  it("waits while the tools query is loading", () => {
    expect(shouldAutoRefreshTools(state({ isLoading: true }))).toBe(false);
  });

  it("does not fire when tools already exist", () => {
    expect(shouldAutoRefreshTools(state({ toolsLength: 3 }))).toBe(false);
  });

  it("does not re-fire once already refreshed this session", () => {
    expect(shouldAutoRefreshTools(state({ alreadyRefreshed: true }))).toBe(
      false,
    );
  });

  it("does not fire while a refresh is already pending", () => {
    expect(shouldAutoRefreshTools(state({ refreshPending: true }))).toBe(false);
  });
});
