import { masonryPreviewHeight } from "@posthog/ui/features/canvas/utils/masonryPreviewHeight";
import { describe, expect, it } from "vitest";

describe("masonryPreviewHeight", () => {
  it("is stable for a key", () => {
    expect(masonryPreviewHeight("canvas:abc")).toBe(
      masonryPreviewHeight("canvas:abc"),
    );
  });

  it("stays inside the bucket set", () => {
    const keys = Array.from({ length: 50 }, (_, i) => `canvas:${i}`);
    const heights = new Set(keys.map(masonryPreviewHeight));
    expect([...heights].every((h) => [168, 224, 288].includes(h))).toBe(true);
  });

  it("staggers across keys so masonry has something to stagger", () => {
    const keys = Array.from({ length: 50 }, (_, i) => `canvas:${i}`);
    expect(new Set(keys.map(masonryPreviewHeight)).size).toBeGreaterThan(1);
  });
});
