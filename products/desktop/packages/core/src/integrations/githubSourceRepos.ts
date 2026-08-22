/**
 * The repositories a warehouse GitHub source syncs. Newer sources carry `repositories`; sources
 * created before multi-repo support only have the single `repository`, which the backend keeps
 * as a server-managed marker once `repositories` exists.
 */
export function effectiveGithubSourceRepos(
  jobInputs: Record<string, unknown> | null | undefined,
): string[] {
  const repositories = jobInputs?.repositories;
  if (Array.isArray(repositories)) {
    const named = repositories.filter(
      (repo): repo is string => typeof repo === "string" && repo.trim() !== "",
    );
    if (named.length > 0) return named;
  }
  const repository = jobInputs?.repository;
  return typeof repository === "string" && repository.trim() !== ""
    ? [repository]
    : [];
}

export function buildGithubRepositoriesPatch(repos: readonly string[]): {
  job_inputs: { repositories: string[] };
} {
  return { job_inputs: { repositories: [...new Set(repos)] } };
}
