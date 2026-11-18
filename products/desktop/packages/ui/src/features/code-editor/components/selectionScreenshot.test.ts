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

  it("keeps the capture inside the frame the selection came from", async () => {
    const captureRegion = vi.fn(
      async (_region: CaptureRegion): Promise<string | null> => null,
    );
    const bounds = { top: 100, left: 300, right: 800, bottom: 600 };

    await captureSelectionScreenshot(
      { captureRegion },
      { top: 310, bottom: 330, endX: 520, bounds },
    );

    const area = captureRegion.mock.calls[0][0];
    expect(area.x).toBeGreaterThanOrEqual(bounds.left);
    expect(area.y).toBeGreaterThanOrEqual(bounds.top);
    expect(area.x + area.width).toBeLessThanOrEqual(bounds.right);
    expect(area.y + area.height).toBeLessThanOrEqual(bounds.bottom);
  });

  it("captures nothing for a selection outside its frame", async () => {
    const captureRegion = vi.fn(
      async (_region: CaptureRegion): Promise<string | null> => null,
    );

    await expect(
      captureSelectionScreenshot(
        { captureRegion },
        {
          top: 20,
          bottom: 40,
          endX: 60,
          bounds: { top: 100, left: 300, right: 800, bottom: 600 },
        },
      ),
    ).resolves.toBeNull();
    expect(captureRegion).not.toHaveBeenCalled();
  });
});
