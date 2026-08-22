import { useQuery } from "@tanstack/react-query";

/**
 * Stars for a public GitHub repo, unauthenticated. A rate-limited or private
 * repo answers with an error, which lands here as null so the caller shows
 * nothing rather than a zero.
 */
export function useRepoStars(source: string | null): number | null {
  const { data } = useQuery({
    queryKey: ["github-repo-stars", source],
    enabled: !!source,
    staleTime: 60 * 60 * 1000,
    retry: 1,
    queryFn: async (): Promise<number | null> => {
      const response = await fetch(`https://api.github.com/repos/${source}`, {
        headers: { Accept: "application/vnd.github+json" },
      });
      if (!response.ok) return null;
      const repo = (await response.json()) as { stargazers_count?: number };
      return typeof repo.stargazers_count === "number"
        ? repo.stargazers_count
        : null;
    },
  });
  return data ?? null;
}
