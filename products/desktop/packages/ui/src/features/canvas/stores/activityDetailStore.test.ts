import { beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/router/routerRef", () => ({
  getRouterOrNull: () => ({ navigate }),
}));

import {
  activityReportIdFromHref,
  clearActivitySelection,
} from "./activityDetailStore";

describe("activityDetailStore", () => {
  beforeEach(() => navigate.mockClear());

  it("identifies persisted Activity report tabs", () => {
    expect(
      activityReportIdFromHref("/activity?item=report-1&report=report-1"),
    ).toBe("report-1");
    expect(
      activityReportIdFromHref("/activity?item=task-1&session=session-1"),
    ).toBeNull();
  });

  it("clears the selected item without leaving Activity", () => {
    clearActivitySelection();

    expect(navigate).toHaveBeenCalledWith({
      to: "/activity",
      search: {},
      replace: true,
    });
  });
});
