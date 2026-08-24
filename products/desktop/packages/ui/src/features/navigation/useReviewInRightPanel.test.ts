import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  channelsLayout: true,
  routeParams: {} as { taskId?: string; channelId?: string },
  fullPath: "/spaces/$channelId/tasks/$taskId",
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => mocks.channelsLayout,
}));
vi.mock("@tanstack/react-router", () => ({
  useParams: () => mocks.routeParams,
  useRouterState: ({
    select,
  }: {
    select: (s: { matches: { fullPath: string }[] }) => unknown;
  }) => select({ matches: [{ fullPath: mocks.fullPath }] }),
}));

import { useActivityDetailStore } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { useReviewInRightPanel } from "./useReviewInRightPanel";

describe("useReviewInRightPanel", () => {
  beforeEach(() => {
    mocks.channelsLayout = true;
    mocks.routeParams = {};
    mocks.fullPath = "/spaces/$channelId/tasks/$taskId";
    useActivityDetailStore.setState({ selected: null });
  });

  it("hands the review to the panel for a task opened through a space", () => {
    mocks.routeParams = { channelId: "chan-1", taskId: "task-1" };

    expect(renderHook(() => useReviewInRightPanel()).result.current).toBe(true);
  });

  // The regression: no channel in the URL left both surfaces drawing the diff.
  it("hands it over for a task read from the activity feed too", () => {
    mocks.fullPath = "/activity";
    useActivityDetailStore.setState({
      selected: { id: "a1", taskId: "task-1", channelId: null },
    });

    expect(renderHook(() => useReviewInRightPanel()).result.current).toBe(true);
  });

  it("leaves it with the session outside the spaces layout", () => {
    mocks.channelsLayout = false;
    mocks.routeParams = { channelId: "chan-1", taskId: "task-1" };

    expect(renderHook(() => useReviewInRightPanel()).result.current).toBe(
      false,
    );
  });
});
