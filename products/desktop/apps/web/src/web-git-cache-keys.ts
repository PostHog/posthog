import type { GitCacheKeyProvider } from "@posthog/ui/features/git-interaction/gitCacheProvider";
import type { QueryFilters } from "@tanstack/react-query";

// The desktop adapter maps these proc-name lookups onto the real tRPC options
// proxy so invalidation keys match the renderer's git/fs read queries. The web
// host has no git/fs router and therefore never issues those reads, so no cache
// entry ever exists under these keys. This adapter only has to produce valid,
// internally-consistent query keys/filters (mirroring tRPC's [[namespace, proc],
// { input }] shape) so the invalidation calls don't throw; they simply match
// nothing.
const key = (
  namespace: "git" | "fs",
  proc: string,
  input?: Record<string, unknown>,
): readonly unknown[] =>
  input === undefined ? [[namespace, proc]] : [[namespace, proc], { input }];

export const webGitCacheKeyProvider: GitCacheKeyProvider = {
  gitQueryFilter: (proc, input): QueryFilters => ({
    queryKey: key("git", proc, input),
  }),
  gitPathFilter: (proc): QueryFilters => ({ queryKey: key("git", proc) }),
  fsPathFilter: (proc): QueryFilters => ({ queryKey: key("fs", proc) }),
  gitQueryKey: (proc, input) => key("git", proc, input),
  fsQueryKey: (proc, input) => key("fs", proc, input),
};
