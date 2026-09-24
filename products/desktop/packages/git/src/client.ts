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
    //
    // The last two cover what `getCleanEnv` sets: the github.com-scoped auth
    // header it passes through `GIT_CONFIG_*`, and the empty `GIT_ASKPASS` that
    // keeps an inherited askpass program from prompting. Both values are ours,
    // never caller input. Without the config opt-in every git call fails with
    // "not permitted without enabling allowUnsafeConfigEnvCount" as soon as a
    // token is present.
    unsafe: {
      allowUnsafeFsMonitor: true,
      allowUnsafeEditor: true,
      allowUnsafePager: true,
      allowUnsafeConfigEnvCount: true,
      allowUnsafeAskPass: true,
    },
    ...rest,
  });
}
