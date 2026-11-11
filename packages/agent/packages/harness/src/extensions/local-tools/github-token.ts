import { readFileSync } from "node:fs";
import {
  GITHUB_TOKEN_ENV_VARS,
  readGithubTokenFromEnv,
} from "@posthog/git/signed-commit";

// helpers for resolving the in-sandbox GitHub token
// Dedicated agentsh credential file (NUL-delimited `key=value` pairs) that the
// PostHog backend rewrites in place when it refreshes GitHub credentials
// mid-session. The agent-server process env is frozen at launch, so reading
// this live file is how in-process tools pick up a refreshed token without a
// process restart.
const SANDBOX_GITHUB_ENV_FILE = "/tmp/agent-github-env";

export function readGithubTokenFromSandboxEnvFile(
  envFilePath: string = SANDBOX_GITHUB_ENV_FILE,
): string | undefined {
  let raw: string;
  try {
    raw = readFileSync(envFilePath, "utf8");
  } catch (err) {
    // A genuinely absent file (local/desktop or test) is unmanaged: signal that so
    // the caller falls back to the process env. But an existing-yet-unreadable file
    // during an actor transition must NOT resurrect the frozen process token, so
    // treat any other read error as an explicit logout (fail closed).
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return undefined;
    }
    return "";
  }
  // The backend logs the sandbox out by truncating this file to zero bytes, so a
  // successfully-read but empty (or whitespace-only) managed file is an explicit
  // logout — return "" so the caller does NOT resurrect the previous actor's token
  // from the frozen launch-time process env. Only an absent file is "unmanaged".
  if (raw.trim() === "") {
    return "";
  }
  const env: Record<string, string> = {};
  for (const entry of raw.split("\0")) {
    const eq = entry.indexOf("=");
    if (eq > 0) {
      env[entry.slice(0, eq)] = entry.slice(eq + 1);
    }
  }
  // A non-empty value wins by the shared token-var precedence.
  const token = readGithubTokenFromEnv(env);
  if (token) {
    return token;
  }
  // The file is the backend's live credential channel. If it carries the token
  // vars but they are emptied, that is an explicit logout on an actor
  // transition — return "" so the caller does NOT resurrect the previous
  // actor's token from the frozen launch-time process env. Only a file with no
  // token vars at all is "unmanaged" and defers to the process env.
  if (GITHUB_TOKEN_ENV_VARS.some((name) => name in env)) {
    return "";
  }
  return undefined;
}

/** The GitHub token available to the sandbox, if any.
 *
 * Prefers the live agentsh env file (refreshed in place mid-session) over the
 * process env (frozen at launch) so long-running in-process tools — e.g. the
 * signed-commit tool — pick up a refreshed token without a restart.
 */
export function resolveGithubToken(
  envFilePath: string = SANDBOX_GITHUB_ENV_FILE,
): string | undefined {
  return (
    readGithubTokenFromSandboxEnvFile(envFilePath) ?? readGithubTokenFromEnv()
  );
}
