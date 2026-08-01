import type { GitCacheKeyProvider } from "@posthog/ui/features/git-interaction/gitCacheProvider";
import { trpc } from "@renderer/trpc";
import type { QueryFilters } from "@tanstack/react-query";

// Desktop adapter: maps the host-agnostic proc-name lookups used by
// @posthog/ui/features/git-interaction/gitCacheKeys onto the real tRPC options
// proxy, so the produced query keys/filters are byte-identical to those used by
// the renderer's read queries.
interface ProcHelpers {
  queryFilter: (input: unknown) => QueryFilters;
  pathFilter: () => QueryFilters;
  queryKey: (input: unknown) => readonly unknown[];
}

const gitProcs = trpc.git as unknown as Record<string, ProcHelpers>;
const fsProcs = trpc.fs as unknown as Record<string, ProcHelpers>;

export const gitCacheKeyProvider: GitCacheKeyProvider = {
  gitQueryFilter: (proc, input) => gitProcs[proc].queryFilter(input),
  gitPathFilter: (proc) => gitProcs[proc].pathFilter(),
  fsPathFilter: (proc) => fsProcs[proc].pathFilter(),
  gitQueryKey: (proc, input) => gitProcs[proc].queryKey(input),
  fsQueryKey: (proc, input) => fsProcs[proc].queryKey(input),
};
