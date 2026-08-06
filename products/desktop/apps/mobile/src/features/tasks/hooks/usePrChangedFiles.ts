import { useQuery } from "@tanstack/react-query";
import { logger } from "@/lib/logger";

const log = logger.scope("usePrChangedFiles");

export type ChangedFileStatus =
  | "added"
  | "removed"
  | "modified"
  | "renamed"
  | "copied"
  | "changed"
  | "unchanged";

export interface ChangedFile {
  filename: string;
  status: ChangedFileStatus;
  additions: number;
  deletions: number;
  previous_filename?: string;
  patch?: string;
}

function parsePrUrl(prUrl: string) {
  const match = prUrl.match(
    /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/,
  );
  if (!match) return null;
  return { owner: match[1], repo: match[2], number: match[3] };
}

export const prChangedFilesKeys = {
  byUrl: (prUrl: string) => ["pr-changed-files", prUrl] as const,
};

// Fetches the file-level diff for a PR via GitHub's public REST API. Public
// repos respond without auth; private repos return 404 — handled as an empty
// list so the screen can render a friendly "no preview" state.
export function usePrChangedFiles(prUrl: string | null | undefined) {
  return useQuery({
    queryKey: prChangedFilesKeys.byUrl(prUrl ?? ""),
    enabled: !!prUrl,
    staleTime: 60_000,
    retry: 1,
    queryFn: async (): Promise<ChangedFile[]> => {
      if (!prUrl) return [];
      const p = parsePrUrl(prUrl);
      if (!p) return [];

      try {
        const res = await fetch(
          `https://api.github.com/repos/${p.owner}/${p.repo}/pulls/${p.number}/files?per_page=100`,
          { headers: { Accept: "application/vnd.github+json" } },
        );
        if (!res.ok) {
          log.info("PR files unavailable", { status: res.status });
          return [];
        }
        return (await res.json()) as ChangedFile[];
      } catch (err) {
        log.warn("Failed to fetch PR files", err);
        return [];
      }
    },
  });
}
