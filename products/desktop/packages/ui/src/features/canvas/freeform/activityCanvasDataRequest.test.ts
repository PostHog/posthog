import type { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createActivityCanvasDataRequest } from "./activityCanvasDataRequest";
import { handleFreeformDataRequest } from "./freeformDataBridge";

vi.mock("./freeformDataBridge", () => ({
  handleFreeformDataRequest: vi.fn().mockResolvedValue({ ok: true }),
}));

describe("createActivityCanvasDataRequest", () => {
  const queryClient = {} as QueryClient;
  const readActivity = vi.fn().mockReturnValue({ rows: [] });

  function request() {
    return createActivityCanvasDataRequest({
      canvasId: "canvas-1",
      sourceVersionId: "version-1",
      readActivity,
      queryClient,
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("answers taskActivity from the panel's task, ignoring any task the canvas names", async () => {
    const result = await request()("taskActivity", {
      limit: 5,
      taskId: "another-task",
    });

    expect(readActivity).toHaveBeenCalledWith(5);
    expect(result).toEqual({ rows: [] });
    expect(handleFreeformDataRequest).not.toHaveBeenCalled();
  });

  it("routes every other method to the canvas-scoped bridge", async () => {
    await request()("stateGet", { key: "draft" });

    expect(readActivity).not.toHaveBeenCalled();
    expect(handleFreeformDataRequest).toHaveBeenCalledWith(
      "stateGet",
      { key: "draft" },
      queryClient,
      { dashboardId: "canvas-1", sourceVersionId: "version-1" },
    );
  });
});
