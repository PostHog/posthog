/**
 * GitHub credentials for the git subprocesses this package spawns, and the
 * settings that keep those subprocesses non-interactive.
 *
 * A git process that cannot authenticate has two bad outcomes with no terminal
 * attached: it blocks on a username prompt nobody can answer, or it silently
 * falls through to SSH on a machine with no agent. Both surface to the user as
 * a dead agent run rather than an error, so every spawn gets these settings.
 */

export const GITHUB_BASE_URL = "https://github.com/";

/**
 * Scoping the auth header to github.com is what keeps the token from being
 * sent to other hosts; an unscoped `http.extraHeader` rides along on every
 * HTTP remote git talks to.
 */
export const GITHUB_AUTH_CONFIG_KEY = `http.${GITHUB_BASE_URL}.extraHeader`;

/** Env var names the GitHub CLI / git credential helper read a token from, in order. */
export const GITHUB_TOKEN_ENV_VARS = ["GH_TOKEN", "GITHUB_TOKEN"] as const;

/** First GitHub token found in `env` (defaults to the process env), if any. */
export function readGithubTokenFromEnv(
  env: Record<string, string | undefined> = process.env,
): string | undefined {
  for (const name of GITHUB_TOKEN_ENV_VARS) {
    if (env[name]) return env[name];
  }
  return undefined;
}

export function ghTokenEnv(token: string): Record<string, string> {
  return Object.fromEntries(GITHUB_TOKEN_ENV_VARS.map((name) => [name, token]));
}

/**
 * `GIT_CONFIG_COUNT` is a single counter shared by everything in the
 * environment, so appending has to start at the count already there. Writing
 * `GIT_CONFIG_KEY_0` unconditionally would drop a caller's own pair.
 */
export function appendGitConfigEnv(
  env: Record<string, string>,
  pairs: readonly (readonly [string, string])[],
): Record<string, string> {
  if (pairs.length === 0) return env;
  const existing = Number.parseInt(env.GIT_CONFIG_COUNT ?? "0", 10);
  const start = Number.isNaN(existing) || existing < 0 ? 0 : existing;
  const next = { ...env };
  pairs.forEach(([key, value], offset) => {
    next[`GIT_CONFIG_KEY_${start + offset}`] = key;
    next[`GIT_CONFIG_VALUE_${start + offset}`] = value;
  });
  next.GIT_CONFIG_COUNT = String(start + pairs.length);
  return next;
}

/**
 * Carries the token as an `http.extraHeader` in the child's environment, so it
 * never reaches `.git/config` the way a credential embedded in the remote URL
 * would.
 */
export function withGithubAuth(
  env: Record<string, string>,
  token: string | undefined,
): Record<string, string> {
  if (!token) return env;
  const basicAuth = Buffer.from(`x-access-token:${token}`).toString("base64");
  return appendGitConfigEnv(env, [
    [GITHUB_AUTH_CONFIG_KEY, `AUTHORIZATION: basic ${basicAuth}`],
  ]);
}

/**
 * Turns a missing credential into an immediate failure instead of a hang: git
 * reports `could not read Username` rather than waiting on a prompt that no
 * agent run can answer, so the caller gets a message it can classify.
 *
 * The ssh equivalent (`BatchMode`) is not set here: it would override whatever
 * `core.sshCommand` the user configured, so the sandbox image sets that one
 * instead, where no user config exists to override.
 */
export function withNonInteractiveGit(
  env: Record<string, string>,
): Record<string, string> {
  // Git resolves an askpass program separately from terminal prompting, so an
  // inherited GIT_ASKPASS or a configured core.askPass can still open a prompt
  // while GIT_TERMINAL_PROMPT is 0. An empty value disables it.
  return { ...env, GIT_TERMINAL_PROMPT: "0", GIT_ASKPASS: "" };
}

// What git prints when it cannot reach the repository with the credential it has.
// The HTTPS forms come from `GIT_TERMINAL_PROMPT=0` refusing to prompt; the ssh form
// from a key no agent can offer. A host-key mismatch is absent: the server's identity
// failed verification, which says nothing about the credential.
const GIT_AUTH_FAILURE_PATTERNS: readonly RegExp[] = [
  /could not read (Username|Password)/i,
  /terminal prompts disabled/i,
  /Authentication failed/i,
  /Invalid username or (token|password)/i,
  /remote: (Repository not found|Invalid username)/i,
  /The requested URL returned error: 40[13]/,
  /Permission denied \(publickey/i,
  /Please make sure you have the correct access rights/i,
];

export function isGitAuthFailure(output: string): boolean {
  return GIT_AUTH_FAILURE_PATTERNS.some((pattern) => pattern.test(output));
}

/**
 * The message a user can act on. Git's own wording for a missing credential
 * names a terminal prompt that was never going to appear, which reads as a
 * bug in the agent rather than as "reconnect GitHub".
 */
export function describeGitAuthFailure(slug: string, detail: string): string {
  return (
    `git could not authenticate to GitHub for ${slug}. ` +
    "Reconnect GitHub in PostHog settings, or check that the connected " +
    `account can reach this repository. Git reported: ${detail}`
  );
}
