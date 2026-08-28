/**
 * When launched from Finder/Spotlight, Electron apps inherit a minimal PATH
 * (/usr/bin:/bin:/usr/sbin:/sbin) instead of the user's shell PATH which
 * includes /opt/homebrew/bin, ~/.local/bin, etc.
 *
 * This reads the PATH from the user's default shell (in login mode) and
 * merges it into process.env.PATH so child processes have access to
 * user-installed binaries.
 *
 * IMPORTANT: We use `-lc` (login, non-interactive) instead of `-ilc`
 * (interactive login) to avoid loading the user's full .zshrc which may
 * include heavy plugins (Oh My Zsh, NVM, thefuck, etc.) that spawn
 * subprocesses and cause zombie process chains when the timeout kills
 * only the parent shell.
 *
 * Because `-lc` skips .zshrc, version-manager paths (nvm, mise, volta) and
 * other entries added there are missing from the resolved shell PATH. We
 * therefore *merge* with the inherited process.env.PATH rather than
 * replacing it — when launched from a terminal (e.g. `pnpm dev`), the
 * inherited PATH already has those entries and must be preserved so git
 * pre-commit hooks (husky, lint-staged, etc.) can find their tools.
 *
 * See: https://github.com/PostHog/code/issues/1399
 */

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { userInfo } from "node:os";
import { dirname, join } from "node:path";
import { getUserDataDir } from "./env";

const DELIMITER = "_SHELL_ENV_DELIMITER_";

const FALLBACK_PATHS = [
  "./node_modules/.bin",
  "/opt/homebrew/bin",
  "/opt/homebrew/sbin",
  "/usr/local/bin",
];

// Regex to strip ANSI escape codes from shell output
const ANSI_REGEX =
  // biome-ignore lint/suspicious/noControlCharactersInRegex: intentional for ANSI stripping
  /[\u001B\u009B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d/#&.:=?%@~_]*)*)?\u0007)|(?:(?:\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-ntqry=><~]))/g;

/** Max age of cached PATH before re-resolving (1 hour) */
const CACHE_MAX_AGE_MS = 60 * 60 * 1000;

function stripAnsi(str: string): string {
  return str.replace(ANSI_REGEX, "");
}

function detectDefaultShell(): string {
  if (process.platform === "win32") {
    return process.env.COMSPEC || "cmd.exe";
  }

  try {
    const { shell } = userInfo();
    if (shell) {
      return shell;
    }
  } catch {
    // userInfo() can throw on some systems
  }

  if (process.platform === "darwin") {
    return process.env.SHELL || "/bin/zsh";
  }

  return process.env.SHELL || "/bin/sh";
}

function getCachePath(): string {
  return join(getUserDataDir(), "shell-env-cache.json");
}

function readCachedPath(): string | undefined {
  try {
    const cachePath = getCachePath();
    if (!existsSync(cachePath)) {
      return undefined;
    }

    const raw = readFileSync(cachePath, "utf-8");
    const cache = JSON.parse(raw) as { path: string; timestamp: number };

    if (Date.now() - cache.timestamp > CACHE_MAX_AGE_MS) {
      return undefined;
    }

    return cache.path;
  } catch {
    return undefined;
  }
}

function writeCachedPath(resolvedPath: string): void {
  try {
    const cachePath = getCachePath();
    const dir = dirname(cachePath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
    writeFileSync(
      cachePath,
      JSON.stringify({ path: resolvedPath, timestamp: Date.now() }),
      "utf-8",
    );
  } catch {
    // Cache write failure is non-fatal
  }
}

function executeShell(shell: string): string | undefined {
  const command = `echo -n "${DELIMITER}"; env; echo -n "${DELIMITER}"; exit`;

  try {
    const result = spawnSync(shell, ["-lc", command], {
      encoding: "utf-8",
      timeout: 5000,
      stdio: ["ignore", "pipe", "ignore"],
      // Kill the entire process group on timeout, not just the parent shell.
      // This prevents orphaned children (node -v, printf, tail, sed) from
      // surviving as zombies.
      killSignal: "SIGKILL",
      env: {
        ...process.env,
        // Disable Oh My Zsh auto-update which can block
        DISABLE_AUTO_UPDATE: "true",
        // Signal to user's shell config that we're resolving the environment.
        // Users with heavy configs can check this and fast-exit:
        //   [[ -n "$POSTHOG_CODE_RESOLVING_ENVIRONMENT" ]] && return
        POSTHOG_CODE_RESOLVING_ENVIRONMENT: "1",
      },
    });

    if (result.status !== 0 && !result.stdout) {
      return undefined;
    }

    return result.stdout || undefined;
  } catch {
    return undefined;
  }
}

function parseEnvOutput(stdout: string): Record<string, string> | undefined {
  const parts = stdout.split(DELIMITER);
  if (parts.length < 2) {
    return undefined;
  }

  const envOutput = stripAnsi(parts[1]);
  const result: Record<string, string> = {};

  for (const line of envOutput.split("\n")) {
    if (!line) continue;
    const eqIndex = line.indexOf("=");
    if (eqIndex > 0) {
      const key = line.slice(0, eqIndex);
      const value = line.slice(eqIndex + 1);
      result[key] = value;
    }
  }

  return result;
}

function getShellPath(shell: string): string | undefined {
  const stdout = executeShell(shell);
  if (!stdout) {
    return undefined;
  }

  const env = parseEnvOutput(stdout);
  return env?.PATH;
}

function mergePaths(sources: (string | undefined)[]): string {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const source of sources) {
    if (!source) continue;
    for (const segment of source.split(":")) {
      if (segment && !seen.has(segment)) {
        seen.add(segment);
        result.push(segment);
      }
    }
  }
  return result.join(":");
}

export function fixPath(): void {
  if (process.platform === "win32") {
    return;
  }

  const originalPath = process.env.PATH;

  const cached = readCachedPath();
  if (cached) {
    process.env.PATH = mergePaths([...FALLBACK_PATHS, originalPath, cached]);
    return;
  }

  const shell = detectDefaultShell();
  const shellPath = getShellPath(shell);

  if (shellPath) {
    const cleaned = stripAnsi(shellPath);
    process.env.PATH = mergePaths([...FALLBACK_PATHS, originalPath, cleaned]);
    writeCachedPath(cleaned);
  } else {
    process.env.PATH = mergePaths([...FALLBACK_PATHS, originalPath]);
  }
}
