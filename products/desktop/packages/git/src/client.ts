import { type SimpleGit, type SimpleGitOptions, simpleGit } from "simple-git";
import { GIT_TRANSPORT_SECURITY_CONFIG } from "./transport-security";

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
  // Transport hardening goes last: git applies later `-c` options over earlier
  // ones, so this wins over PERFORMANCE_CONFIG, any caller config, and the
  // repository's own `.git/config` (see transport-security.ts).
  const config = [
    ...PERFORMANCE_CONFIG,
    ...(callerConfig ?? []),
    ...GIT_TRANSPORT_SECURITY_CONFIG,
  ];
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
    // allowUnsafeProtocolOverride is required to pass any `protocol.*` config at
    // all: simple-git rejects the whole key space on remote tasks rather than
    // judging the value, so it blocks the hardening in
    // GIT_TRANSPORT_SECURITY_CONFIG along with an attacker's `=always`. Its
    // guard is redundant here because that config is appended last and git
    // applies the last `-c` for a key, so no caller can widen the policy.
    unsafe: {
      allowUnsafeFsMonitor: true,
      allowUnsafeEditor: true,
      allowUnsafePager: true,
      allowUnsafeProtocolOverride: true,
    },
    ...rest,
  });
}
