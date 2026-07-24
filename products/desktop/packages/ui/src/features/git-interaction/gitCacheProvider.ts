import type { QueryFilters } from "@tanstack/react-query";

export interface GitCacheKeyProvider {
  /** `trpc.git.<proc>.queryFilter(input)` */
  gitQueryFilter(proc: string, input: Record<string, unknown>): QueryFilters;
  /** `trpc.git.<proc>.pathFilter()` */
  gitPathFilter(proc: string): QueryFilters;
  /** `trpc.fs.<proc>.pathFilter()` */
  fsPathFilter(proc: string): QueryFilters;
  /** `trpc.git.<proc>.queryKey(input)` */
  gitQueryKey(
    proc: string,
    input?: Record<string, unknown>,
  ): readonly unknown[];
  /** `trpc.fs.<proc>.queryKey(input)` */
  fsQueryKey(proc: string, input?: Record<string, unknown>): readonly unknown[];
}

export const GIT_CACHE_KEY_PROVIDER = Symbol.for(
  "posthog.ui.GitCacheKeyProvider",
);
