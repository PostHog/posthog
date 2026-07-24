import { useQuery } from "@tanstack/react-query";
import { logger } from "@/lib/logger";

const log = logger.scope("usePrStatus");

export interface PrStatus {
  state: "open" | "closed";
  merged: boolean;
  draft: boolean;
  additions: number;
  deletions: number;
}

function parsePrUrl(
  prUrl: string,
): { owner: string; repo: string; number: string } | null {
  const match = prUrl.match(
    /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/,
  );
  if (!match) return null;
  return { owner: match[1], repo: match[2], number: match[3] };
}

export const prStatusKeys = {
  byUrl: (prUrl: string) => ["pr-status", prUrl] as const,
};

// Fetches PR state via GitHub's public REST API. Public repos respond without
// auth; private repos return 404 — in that case we resolve to `null` and the
// UI falls back to a neutral icon (still tappable to open the PR).
export function usePrStatus(prUrl: string | null | undefined) {
  return useQuery({
    queryKey: prStatusKeys.byUrl(prUrl ?? ""),
    enabled: !!prUrl,
    staleTime: 60_000,
    retry: 1,
    queryFn: async (): Promise<PrStatus | null> => {
      if (!prUrl) return null;
      const parsed = parsePrUrl(prUrl);
      if (!parsed) return null;

      try {
        const res = await fetch(
          `https://api.github.com/repos/${parsed.owner}/${parsed.repo}/pulls/${parsed.number}`,
          { headers: { Accept: "application/vnd.github+json" } },
        );
        if (!res.ok) {
          log.info("PR details unavailable", { status: res.status });
          return null;
        }
        const data = (await res.json()) as {
          state: string;
          merged: boolean;
          draft: boolean;
          additions?: number;
          deletions?: number;
        };
        return {
          state: data.state === "closed" ? "closed" : "open",
          merged: !!data.merged,
          draft: !!data.draft,
          additions: data.additions ?? 0,
          deletions: data.deletions ?? 0,
        };
      } catch (err) {
        log.warn("Failed to fetch PR status", err);
        return null;
      }
    },
  });
}
