export const SKETCHPAD_CACHE_DIR_SEGMENTS = [
  ".posthog-code",
  "sketchpads",
  "cache",
] as const;

export function sketchpadCacheFilePath(
  homeDir: string,
  sketchpadId: string,
): string {
  const safeId = sketchpadId.replace(/[^a-zA-Z0-9_-]/g, "_");
  return [homeDir, ...SKETCHPAD_CACHE_DIR_SEGMENTS, `${safeId}.json`].join("/");
}
