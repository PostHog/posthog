// Masonry needs cards of differing height or it degrades into a ragged grid.
// Canvas previews have no intrinsic height to measure (the app is rendered into
// a clipped, scaled frame), so each card gets a stable height picked from its
// key — same canvas, same height across renders and reloads, no layout churn.
const MASONRY_HEIGHTS = [168, 224, 288] as const;

export function masonryPreviewHeight(key: string): number {
  let hash = 0;
  for (let i = 0; i < key.length; i++) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return MASONRY_HEIGHTS[hash % MASONRY_HEIGHTS.length];
}
