import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import {
  useComposerPanelCollapsed,
  useComposerPanelStore,
} from "./composerPanelStore";

const collapsedIds = () =>
  useComposerPanelStore.getState().collapsedToolCallIds;
const setCollapsed = (toolCallId: string, collapsed: boolean) =>
  useComposerPanelStore.getState().setCollapsed(toolCallId, collapsed);

describe("composerPanelStore", () => {
  beforeEach(() => {
    useComposerPanelStore.setState({
      collapsedToolCallIds: [],
      hasHydrated: true,
    });
  });

  it("holds a closed panel and drops it when it opens again", () => {
    setCollapsed("plan-1", true);
    expect(collapsedIds()).toEqual(["plan-1"]);

    setCollapsed("plan-1", false);
    expect(collapsedIds()).toEqual([]);
  });

  it("records an id once, however many times it is closed", () => {
    setCollapsed("plan-1", true);
    setCollapsed("plan-1", true);

    expect(collapsedIds()).toEqual(["plan-1"]);
  });

  it.each([
    { name: "an id it has not read yet", hasHydrated: false, expected: true },
    { name: "an id it has read", hasHydrated: true, expected: false },
  ])("reports $name as collapsed: $expected", ({ hasHydrated, expected }) => {
    // Until the persisted list arrives, every panel reads as closed: opening
    // them all for a frame after a reload would flash the overlay too.
    useComposerPanelStore.setState({ hasHydrated });

    const { result } = renderHook(() => useComposerPanelCollapsed("plan-1"));

    expect(result.current).toBe(expected);
  });

  it("evicts the stalest ids so the persisted list stays bounded", () => {
    for (let i = 0; i < 60; i++) setCollapsed(`plan-${i}`, true);

    const ids = collapsedIds();
    expect(ids).toHaveLength(50);
    expect(ids[0]).toBe("plan-10");
    expect(ids.at(-1)).toBe("plan-59");
  });

  it("keeps an id that is closed again from being evicted as the stalest", () => {
    for (let i = 0; i < 50; i++) setCollapsed(`plan-${i}`, true);
    setCollapsed("plan-0", true);
    setCollapsed("plan-50", true);

    expect(collapsedIds()).toContain("plan-0");
    expect(collapsedIds()).not.toContain("plan-1");
  });
});
