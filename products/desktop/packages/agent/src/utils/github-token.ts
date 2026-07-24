import { readFileSync } from "node:fs";
import { readGithubTokenFromEnv } from "@posthog/git/signed-commit";

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
  try {
    const raw = readFileSync(envFilePath, "utf8");
    const env: Record<string, string> = {};
    for (const entry of raw.split("\0")) {
      const eq = entry.indexOf("=");
      if (eq > 0) {
        env[entry.slice(0, eq)] = entry.slice(eq + 1);
      }
    }
    // Reuse the shared token-var allowlist + precedence instead of hardcoding.
    return readGithubTokenFromEnv(env);
  } catch {
    // No env file (local/desktop or test) — fall back to the process env.
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
