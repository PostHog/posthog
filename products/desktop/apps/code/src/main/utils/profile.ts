/**
 * Dev profiles — several copies of the app running side by side, each signed in
 * as a different user, so multiplayer features can be exercised without a
 * second machine.
 *
 * A profile is just a name that suffixes the two things which make an instance
 * exclusive: the app name backing `requestSingleInstanceLock()`, and the
 * `userData` directory holding `posthog-code.db` (the encrypted refresh token
 * lives there). Separate lock, separate session — no window, session-partition,
 * or auth-service changes needed, because each instance is its own process.
 *
 * Dev builds only. Pure functions over argv/env so bootstrap can call them
 * before Electron is configured.
 */

const PROFILE_ENV_VAR = "POSTHOG_CODE_PROFILE";
const PROFILE_ARG_PREFIX = "--posthog-profile=";
const MAX_PROFILE_LENGTH = 24;

export class InvalidProfileError extends Error {}

/**
 * Reads the requested profile from `--posthog-profile=<name>` or
 * `POSTHOG_CODE_PROFILE`, preferring the flag. Returns null when neither is
 * set, or when `isDev` is false — a packaged app always uses the single
 * default profile.
 *
 * Throws `InvalidProfileError` rather than falling back to the default: a
 * typo'd name that silently shared the default profile's login would defeat
 * the point of asking for one.
 */
export function resolveProfile(
  argv: readonly string[],
  env: NodeJS.ProcessEnv,
  isDev: boolean,
): string | null {
  if (!isDev) return null;

  const fromArg = argv
    .find((arg) => arg.startsWith(PROFILE_ARG_PREFIX))
    ?.slice(PROFILE_ARG_PREFIX.length);
  const requested = fromArg ?? env[PROFILE_ENV_VAR];
  if (requested === undefined || requested.trim() === "") return null;

  const normalized = requested
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");

  if (normalized === "") {
    throw new InvalidProfileError(
      `Profile "${requested}" has no letters or digits. Use a name like "alice".`,
    );
  }
  if (normalized.length > MAX_PROFILE_LENGTH) {
    throw new InvalidProfileError(
      `Profile "${requested}" is longer than ${MAX_PROFILE_LENGTH} characters.`,
    );
  }
  return normalized;
}

/** Suffix appended to per-instance identities. Empty for the default profile. */
export function profileSuffix(profile: string | null): string {
  return profile === null ? "" : `-profile-${profile}`;
}

/** Window title / dock name marker, e.g. `PostHog (Development · alice)`. */
export function profileLabel(profile: string | null): string {
  return profile === null ? "" : ` · ${profile}`;
}

/**
 * Per-profile default CDP port so two dev instances do not both try to bind
 * 9222 (Chromium loses the second one silently). Derived from the name so it is
 * stable across restarts and printable in the boot log; `POSTHOG_CODE_CDP_PORT`
 * still wins when set explicitly.
 */
export function defaultCdpPort(
  profile: string | null,
  basePort = 9222,
): number {
  if (profile === null) return basePort;
  let hash = 0;
  for (const char of profile) {
    hash = (hash * 31 + char.charCodeAt(0)) % 100;
  }
  return basePort + 1 + hash;
}
