import type { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createActivityCanvasDataRequest } from "./activityCanvasDataRequest";
import { handleFreeformDataRequest } from "./freeformDataBridge";

vi.mock("./freeformDataBridge", () => ({
  handleFreeformDataRequest: vi.fn().mockResolvedValue({ ok: true }),
}));

describe("createActivityCanvasDataRequest", () => {
  const queryClient = {} as QueryClient;
  const readFeed = vi.fn().mockReturnValue({ rows: [] });

  function request() {
    return createActivityCanvasDataRequest({
      canvasId: "canvas-1",
      sourceVersionId: "version-1",
      readFeed,
      queryClient,
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("answers activityFeed from the viewer's own feed, ignoring what the canvas names", async () => {
    const result = await request()("activityFeed", {
      limit: 5,
      userId: "someone-else",
    });

    expect(readFeed).toHaveBeenCalledWith(5);
    expect(result).toEqual({ rows: [] });
    expect(handleFreeformDataRequest).not.toHaveBeenCalled();
  });

  it("routes every other method to the canvas-scoped bridge", async () => {
    await request()("stateGet", { key: "draft" });

    expect(readFeed).not.toHaveBeenCalled();
    expect(handleFreeformDataRequest).toHaveBeenCalledWith(
      "stateGet",
      { key: "draft" },
      queryClient,
      { dashboardId: "canvas-1", sourceVersionId: "version-1" },
    );
  });
});
