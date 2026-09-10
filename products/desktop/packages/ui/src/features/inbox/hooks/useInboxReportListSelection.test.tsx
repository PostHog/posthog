import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useInboxReportSelectionStore } from "../stores/inboxReportSelectionStore";
import { useInboxReportListSelection } from "./useInboxReportListSelection";

describe("useInboxReportListSelection", () => {
  beforeEach(() => {
    useInboxReportSelectionStore.setState({
      selectedReportIds: [],
      lastClickedId: null,
      orderedReportIds: [],
    });
  });

  it("clears the selection and the range anchor when the list unmounts", () => {
    const { unmount } = renderHook(
      ({ ids }) => useInboxReportListSelection(ids),
      { initialProps: { ids: ["r1", "r2", "r3"] } },
    );
    act(() => {
      useInboxReportSelectionStore.setState({
        selectedReportIds: ["r1", "r2"],
        lastClickedId: "r2",
      });
    });

    unmount();

    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
      [],
    );
    expect(useInboxReportSelectionStore.getState().lastClickedId).toBeNull();
  });

  it("keeps the selection when only the rendered order changes", () => {
    const { rerender } = renderHook(
      ({ ids }) => useInboxReportListSelection(ids),
      { initialProps: { ids: ["r1", "r2", "r3"] } },
    );
    act(() => {
      useInboxReportSelectionStore.setState({
        selectedReportIds: ["r2"],
        lastClickedId: "r2",
      });
    });

    rerender({ ids: ["r2", "r3"] });

    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual([
      "r2",
    ]);
    expect(useInboxReportSelectionStore.getState().lastClickedId).toBe("r2");
  });
});
