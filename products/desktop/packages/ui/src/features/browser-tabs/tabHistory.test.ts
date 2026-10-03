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
});
