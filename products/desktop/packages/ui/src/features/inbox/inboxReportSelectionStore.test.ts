import { beforeEach, describe, expect, it } from "vitest";
import { useInboxReportSelectionStore } from "./stores/inboxReportSelectionStore";

describe("inboxReportSelectionStore", () => {
  beforeEach(() => {
    useInboxReportSelectionStore.setState({
      selectedReportIds: [],
      lastClickedId: null,
    });
  });

  it("starts empty", () => {
    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
      [],
    );
    expect(useInboxReportSelectionStore.getState().lastClickedId).toBeNull();
  });

  it("setSelectedReportIds de-duplicates ids", () => {
    useInboxReportSelectionStore
      .getState()
      .setSelectedReportIds(["r1", "r2", "r1", "r3", "r2"]);

    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual([
      "r1",
      "r2",
      "r3",
    ]);
  });

  it("setSelectedReportIds with a single id sets lastClickedId", () => {
    useInboxReportSelectionStore.getState().setSelectedReportIds(["r1"]);

    expect(useInboxReportSelectionStore.getState().lastClickedId).toBe("r1");
  });

  it("setSelectedReportIds with multiple ids preserves existing lastClickedId", () => {
    useInboxReportSelectionStore.setState({ lastClickedId: "r1" });
    useInboxReportSelectionStore.getState().setSelectedReportIds(["r2", "r3"]);

    expect(useInboxReportSelectionStore.getState().lastClickedId).toBe("r1");
  });

  it("toggleReportSelection adds an unselected report", () => {
    useInboxReportSelectionStore.getState().toggleReportSelection("r1");

    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual([
      "r1",
    ]);
    expect(useInboxReportSelectionStore.getState().lastClickedId).toBe("r1");
  });

  it("toggleReportSelection removes a selected report", () => {
    useInboxReportSelectionStore.setState({
      selectedReportIds: ["r1", "r2"],
    });

    useInboxReportSelectionStore.getState().toggleReportSelection("r1");

    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual([
      "r2",
    ]);
    expect(useInboxReportSelectionStore.getState().lastClickedId).toBe("r1");
  });

  it("isReportSelected reflects selection state", () => {
    useInboxReportSelectionStore.setState({
      selectedReportIds: ["r2"],
    });

    expect(useInboxReportSelectionStore.getState().isReportSelected("r1")).toBe(
      false,
    );
    expect(useInboxReportSelectionStore.getState().isReportSelected("r2")).toBe(
      true,
    );
  });

  it("clearSelection clears all selected reports and lastClickedId", () => {
    useInboxReportSelectionStore.setState({
      selectedReportIds: ["r1", "r2"],
      lastClickedId: "r2",
    });

    useInboxReportSelectionStore.getState().clearSelection();

    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
      [],
    );
    expect(useInboxReportSelectionStore.getState().lastClickedId).toBeNull();
  });

  it("pruneSelection keeps only visible report ids", () => {
    useInboxReportSelectionStore.setState({
      selectedReportIds: ["r1", "r2", "r3"],
    });

    useInboxReportSelectionStore.getState().pruneSelection(["r2", "r4"]);

    expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual([
      "r2",
    ]);
  });

  describe("selectRange", () => {
    const orderedIds = ["r1", "r2", "r3", "r4", "r5"];

    it("selects a forward range from anchor to target", () => {
      useInboxReportSelectionStore.setState({ lastClickedId: "r2" });

      useInboxReportSelectionStore.getState().selectRange("r4", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r2", "r3", "r4"],
      );
    });

    it("selects a backward range from anchor to target", () => {
      useInboxReportSelectionStore.setState({ lastClickedId: "r4" });

      useInboxReportSelectionStore.getState().selectRange("r2", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r2", "r3", "r4"],
      );
    });

    it("merges range with existing selection", () => {
      useInboxReportSelectionStore.setState({
        selectedReportIds: ["r1"],
        lastClickedId: "r3",
      });

      useInboxReportSelectionStore.getState().selectRange("r5", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r1", "r3", "r4", "r5"],
      );
    });

    it("selects just the target when there is no anchor", () => {
      useInboxReportSelectionStore.getState().selectRange("r3", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r3"],
      );
    });

    it("selects just the target when anchor is not in the ordered list", () => {
      useInboxReportSelectionStore.setState({ lastClickedId: "r99" });

      useInboxReportSelectionStore.getState().selectRange("r3", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r3"],
      );
    });

    it("updates lastClickedId to the target", () => {
      useInboxReportSelectionStore.setState({ lastClickedId: "r1" });

      useInboxReportSelectionStore.getState().selectRange("r3", orderedIds);

      expect(useInboxReportSelectionStore.getState().lastClickedId).toBe("r3");
    });
  });

  describe("selectExactRange", () => {
    const orderedIds = ["r1", "r2", "r3", "r4", "r5"];

    it("selects exactly the range from anchor to target", () => {
      useInboxReportSelectionStore
        .getState()
        .selectExactRange("r2", "r4", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r2", "r3", "r4"],
      );
    });

    it("replaces existing selection instead of merging", () => {
      useInboxReportSelectionStore.setState({
        selectedReportIds: ["r1", "r5"],
      });

      useInboxReportSelectionStore
        .getState()
        .selectExactRange("r2", "r4", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r2", "r3", "r4"],
      );
    });

    it("keeps lastClickedId as the anchor", () => {
      useInboxReportSelectionStore
        .getState()
        .selectExactRange("r2", "r4", orderedIds);

      expect(useInboxReportSelectionStore.getState().lastClickedId).toBe("r2");
    });

    it("contracts selection when cursor moves back toward anchor", () => {
      // Simulate: anchor=r2, extend to r4, then contract back to r3
      useInboxReportSelectionStore
        .getState()
        .selectExactRange("r2", "r4", orderedIds);
      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r2", "r3", "r4"],
      );

      useInboxReportSelectionStore
        .getState()
        .selectExactRange("r2", "r3", orderedIds);
      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r2", "r3"],
      );
    });

    it("works in reverse direction", () => {
      useInboxReportSelectionStore
        .getState()
        .selectExactRange("r4", "r2", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r2", "r3", "r4"],
      );
      expect(useInboxReportSelectionStore.getState().lastClickedId).toBe("r4");
    });

    it("selects just the target when anchor is not in the ordered list", () => {
      useInboxReportSelectionStore
        .getState()
        .selectExactRange("r99", "r3", orderedIds);

      expect(useInboxReportSelectionStore.getState().selectedReportIds).toEqual(
        ["r3"],
      );
    });
  });
});
