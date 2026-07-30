import type { RepositoryProvider } from "@posthog/shared/analytics-events";
import type { DetectedRepo } from "./steps";

export interface DetectRepoResult {
  organization: string;
  repository: string;
  remote?: string | null;
  branch?: string | null;
}

export function inferRepositoryProvider(
  remote: string | undefined,
): RepositoryProvider {
  if (!remote) return "local";
  const host = remote
    .match(/^(?:[a-z]+:\/\/)?(?:[^@/]+@)?([a-z0-9.-]+)[:/]/i)?.[1]
    ?.toLowerCase();
  if (host === "gitlab.com") return "gitlab";
  if (host === "github.com") return "github";
  return "none";
}

export function toDetectedRepo(
  result: DetectRepoResult | null | undefined,
): DetectedRepo | null {
  if (!result) return null;
  return {
    organization: result.organization,
    repository: result.repository,
    fullName: `${result.organization}/${result.repository}`,
    remote: result.remote ?? undefined,
    branch: result.branch ?? undefined,
  };
}

export function repoMatchesGitHubRepos(
  detectedRepo: DetectedRepo | null,
  repositories: string[],
): boolean {
  if (!detectedRepo || repositories.length === 0) return false;
  const target = detectedRepo.fullName.toLowerCase();
  return repositories.some((repo) => repo.toLowerCase() === target);
}
