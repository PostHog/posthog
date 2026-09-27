import type { CaptureRegion } from "@posthog/platform/screen-capture";
import { describe, expect, it, vi } from "vitest";
import { captureSelectionScreenshot } from "./selectionScreenshot";

describe("captureSelectionScreenshot", () => {
  it("captures the whole selection, from its start to its end", async () => {
    const captureRegion = vi.fn(
      async (_region: CaptureRegion): Promise<string | null> => null,
    );

    await captureSelectionScreenshot(
      { captureRegion },
      { top: 300, bottom: 318, endX: 700, startX: 40, startTop: 200 },
    );

    const area = captureRegion.mock.calls[0][0];
    expect(area.x).toBeLessThanOrEqual(40);
    expect(area.x + area.width).toBeGreaterThanOrEqual(700);
    expect(area.y).toBeLessThanOrEqual(200);
    expect(area.y + area.height).toBeGreaterThanOrEqual(318);
  });
});
