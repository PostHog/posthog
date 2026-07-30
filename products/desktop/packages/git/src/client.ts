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
    ...rest,
  });
}
