export const CANVAS_V2_CACHE_DIR_SEGMENTS = [
  ".posthog-code",
  "canvases-v2",
  "cache",
] as const;

export function canvasV2CacheFilePath(
  homeDir: string,
  boardId: string,
): string {
  const safeId = boardId.replace(/[^a-zA-Z0-9_-]/g, "_");
  return [homeDir, ...CANVAS_V2_CACHE_DIR_SEGMENTS, `${safeId}.json`].join("/");
}
