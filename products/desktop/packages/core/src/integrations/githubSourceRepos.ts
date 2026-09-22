import type { ExternalDataSource } from "@posthog/api-client/posthog-client";

/** The only GitHub table Self-driving reads. */
const ISSUES_ENDPOINT = "issues";

/**
 * Full table replication. Issues get edited and closed after they are created, so an append-only
 * sync would miss everything that happens to an issue after PostHog first saw it.
 */
export const GITHUB_ISSUES_SYNC_TYPE = "full_refresh";

/** GitHub full names are case-insensitive, and the backend lowercases them before naming rows. */
function normalizeRepo(repo: string): string {
  return repo.trim().toLowerCase();
}

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

/**
 * The team GitHub installation a source authenticates through. Null for a source connected with a
 * personal access token, which carries no installation to scope a repository list by.
 */
export function githubSourceIntegrationId(
  jobInputs: Record<string, unknown> | null | undefined,
): number | null {
  const authMethod = jobInputs?.auth_method;
  if (typeof authMethod !== "object" || authMethod === null) return null;
  const id = (authMethod as Record<string, unknown>).github_integration_id;
  if (typeof id === "number") return Number.isFinite(id) ? id : null;
  if (typeof id !== "string" || id.trim() === "") return null;
  const parsed = Number(id);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * The names the backend gives each repository's `issues` schema row. Rows are named
 * `owner/repo.issues`, except on a source created before multi-repo support, where that one
 * repository's rows keep the bare endpoint name forever.
 */
export function githubIssuesSchemaNames(
  repos: readonly string[],
  jobInputs?: Record<string, unknown> | null,
): string[] {
  const legacyRepo =
    typeof jobInputs?.repository === "string"
      ? normalizeRepo(jobInputs.repository)
      : "";
  return [
    ...new Set(
      repos.map((repo) => {
        const normalized = normalizeRepo(repo);
        return normalized && normalized === legacyRepo
          ? ISSUES_ENDPOINT
          : `${normalized}.${ISSUES_ENDPOINT}`;
      }),
    ),
  ];
}

/**
 * The schema rows that still have to be switched on for `repos` to reach the inbox. Adding a
 * repository to a source creates its rows disabled, so its issues never sync until something
 * enables them — pass the source as re-read after the repositories were saved.
 */
export function githubIssuesSchemasToEnable(
  repos: readonly string[],
  source: Pick<ExternalDataSource, "job_inputs" | "schemas"> | undefined,
): { id: string }[] {
  const schemas = Array.isArray(source?.schemas) ? source.schemas : [];
  const wanted = new Set(githubIssuesSchemaNames(repos, source?.job_inputs));
  return schemas.filter(
    (schema) =>
      wanted.has(schema.name) &&
      (!schema.should_sync || schema.sync_type !== GITHUB_ISSUES_SYNC_TYPE),
  );
}
