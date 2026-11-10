import { type SimpleGit, type SimpleGitOptions, simpleGit } from "simple-git";

export type GitClient = SimpleGit;

export interface CreateGitClientOptions extends Partial<SimpleGitOptions> {
  abortSignal?: AbortSignal;
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
  const { abortSignal: signal, config: callerConfig, ...rest } = options ?? {};
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
    },
    ...rest,
  });
}
