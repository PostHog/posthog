import { beforeEach, describe, expect, it } from "vitest";
import { useReportChatPanelStore } from "./reportChatPanelStore";

describe("reportChatPanelStore", () => {
  beforeEach(() => {
    useReportChatPanelStore.setState({ pendingQuoteByReport: {} });
  });

  it("hands a pending quote to only one consumer", () => {
    const store = useReportChatPanelStore.getState();
    store.setPendingQuote("report-1", "> selected text");

    expect(store.takePendingQuote("report-1")).toBe("> selected text");
    expect(store.takePendingQuote("report-1")).toBeNull();
  });
});
