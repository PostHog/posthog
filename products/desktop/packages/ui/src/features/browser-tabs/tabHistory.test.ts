import { createMemoryHistory } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";
import { pushTabHistoryEntry } from "./tabHistory";

describe("pushTabHistoryEntry", () => {
  it("selects a different tab even when both tabs have the same href", () => {
    const history = createMemoryHistory({ initialEntries: ["/inbox"] });
    pushTabHistoryEntry(history, "/inbox", "tab-a");

    pushTabHistoryEntry(history, "/inbox", "tab-b");

    expect(history.location.href).toBe("/inbox");
    expect(history.location.state.tabId).toBe("tab-b");
    expect(history.length).toBe(3);
  });

  it("restores each report tab's source instead of inheriting the outgoing tab's", () => {
    const history = createMemoryHistory({
      initialEntries: ["/settings/agents"],
    });
    pushTabHistoryEntry(history, "/reports/first", "tab-a", "/settings/agents");
    pushTabHistoryEntry(history, "/reports/second", "tab-b", "/spaces/space-1");
    expect(history.location.state.reportSourceHref).toBe("/spaces/space-1");
    history.back();
    expect(history.location.href).toBe("/reports/first");
    expect(history.location.state.reportSourceHref).toBe("/settings/agents");
    history.back();
    expect(history.location.href).toBe("/settings/agents");
    history.forward();
    expect(history.location.state.reportSourceHref).toBe("/settings/agents");
  });

  it("opens an independent report tab with neutral navigation", () => {
    const history = createMemoryHistory({ initialEntries: ["/"] });
    pushTabHistoryEntry(history, "/reports/first", "tab-a", "/settings/agents");
    pushTabHistoryEntry(history, "/reports/second", "tab-b");
    expect(history.location.state.reportSourceHref).toBeUndefined();
  });
});
