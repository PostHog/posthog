const STORAGE_KEY = "ph-dev-flags-off";

/**
 * Flags forced off for local development, as a comma-separated list under
 * `ph-dev-flags-off` in localStorage:
 *
 *   localStorage.setItem("ph-dev-flags-off", "project-bluebird,code-spaces-layout")
 *
 * Dev builds default several flags on (`useFeatureFlag(key, import.meta.env.DEV)`),
 * and posthog's own override cannot undo that — the default is applied after it.
 * Without this there is no way to see the flag-off app short of editing source.
 *
 * Read once at module load: which flags are off is a boot-time choice, and a
 * flag flipping mid-session is not what a flag-off user sees.
 */
const forcedOff: ReadonlySet<string> = (() => {
  if (!import.meta.env.DEV) return new Set<string>();
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY) ?? "";
    return new Set(
      raw
        .split(",")
        .map((key) => key.trim())
        .filter(Boolean),
    );
  } catch {
    return new Set<string>();
  }
})();

export function isFlagForcedOff(flagKey: string): boolean {
  return forcedOff.has(flagKey);
}
