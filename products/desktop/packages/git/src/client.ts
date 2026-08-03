import { type SimpleGit, type SimpleGitOptions, simpleGit } from "simple-git";

export type GitClient = SimpleGit;

export interface CreateGitClientOptions extends Partial<SimpleGitOptions> {
  abortSignal?: AbortSignal;
  /**
   * Opt in to `GIT_CONFIG_COUNT`-style config in the `env` passed to the
   * client. Only for callers that build that env themselves (e.g. injecting an
   * `http.extraHeader` token) — leaving it off keeps simple-git's guard against
   * config smuggled in through the inherited environment.
   */
  allowConfigEnv?: boolean;
}

export const PERFORMANCE_CONFIG = [
  "core.untrackedCache=true",
  "core.fsmonitor=true",
  "core.preloadIndex=true",
];

export function createGitClient(
  baseDir?: string,
  options?: CreateGitClientOptions,
): GitClient {
  const {
    abortSignal: signal,
    config: callerConfig,
    allowConfigEnv,
    ...rest
  } = options ?? {};
  const config = callerConfig
    ? [...PERFORMANCE_CONFIG, ...callerConfig]
    : PERFORMANCE_CONFIG;
  return simpleGit({
    baseDir,
    maxConcurrentProcesses: 6,
    trimmed: true,
    abort: signal,
    config,
    // simple-git >=3.36 blocks the hardcoded core.fsmonitor perf flag and the
    // inherited GIT_EDITOR/PAGER env by default. These are trusted values on the
    // user's own machine, not the untrusted protocol.allow injection the CVEs
    // addressed, so opt in explicitly.
    unsafe: {
      allowUnsafeFsMonitor: true,
      allowUnsafeEditor: true,
      allowUnsafePager: true,
      ...(allowConfigEnv && { allowUnsafeConfigEnvCount: true }),
    },
    ...rest,
  });
}
