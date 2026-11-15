// GitLab (gitlab.com) helpers for cloud runs that work in a GitLab project.
// The backend starts such runs with POSTHOG_GIT_PROVIDER=gitlab and
// GITLAB_TOKEN, and clones the repo with the token in the origin URL.

export const GITLAB_DEFAULT_HOST = "gitlab.com";

const REQUEST_TIMEOUT_MS = 15_000;

export function isGitlabRun(
  env: Record<string, string | undefined> = process.env,
): boolean {
  return env.POSTHOG_GIT_PROVIDER?.trim().toLowerCase() === "gitlab";
}

export interface GitlabClient {
  token: string;
  host: string;
  /** Injectable for tests. Defaults to the global fetch. */
  fetch?: typeof fetch;
}

export function resolveGitlabClient(
  env: Record<string, string | undefined> = process.env,
): GitlabClient | null {
  const token = env.GITLAB_TOKEN?.trim();
  if (!token) return null;
  return {
    token,
    host: GITLAB_DEFAULT_HOST,
  };
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// GitLab allows letters, digits, `_`, `-` and `.` in each path segment. The
// strict charset keeps a crafted value out of git arguments and REST paths.
const PATH_SEGMENT = "[A-Za-z0-9_.][A-Za-z0-9_.-]*";
const PATH_SEGMENT_REGEX = new RegExp(`^${PATH_SEGMENT}$`);

function isSafeProjectPath(path: string): boolean {
  const segments = path.split("/");
  return (
    segments.length >= 2 &&
    segments.every((s) => PATH_SEGMENT_REGEX.test(s) && s !== "." && s !== "..")
  );
}

/**
 * The full project path (`group/sub/project`) of a GitLab remote URL, or null
 * for another host. Accepts HTTPS (with or without credentials) and scp-style
 * SSH remotes.
 */
export function parseGitlabRemoteProject(
  remoteUrl: string | null | undefined,
  host: string = GITLAB_DEFAULT_HOST,
): string | null {
  if (!remoteUrl) return null;
  const pattern = new RegExp(
    `^(?:https?://(?:[^@/\\s]+@)?|ssh://git@|git@)${escapeRegExp(host)}[:/](.+)$`,
    "i",
  );
  const match = pattern.exec(remoteUrl.trim());
  if (!match) return null;
  const path = match[1].replace(/\/+$/, "").replace(/\.git$/i, "");
  return isSafeProjectPath(path) ? path : null;
}

export interface GitlabMergeRequestRef {
  projectPath: string;
  iid: number;
}

export function parseGitlabMergeRequestUrl(
  url: string | null | undefined,
  host: string = GITLAB_DEFAULT_HOST,
): GitlabMergeRequestRef | null {
  if (!url) return null;
  const pattern = new RegExp(
    `^https://${escapeRegExp(host)}/((?:${PATH_SEGMENT}/)+?${PATH_SEGMENT})` +
      `/-/merge_requests/([1-9]\\d*)/?(?:[?#].*)?$`,
    "i",
  );
  const match = pattern.exec(url.trim());
  if (!match) return null;
  if (!isSafeProjectPath(match[1])) return null;
  return { projectPath: match[1], iid: Number(match[2]) };
}

export class GitlabApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "GitlabApiError";
  }
}

function projectApiPath(projectPath: string): string {
  return `/projects/${encodeURIComponent(projectPath)}`;
}

// GitLab error bodies carry `message` (a string, an array, or a field map) or
// `error`. Only that text goes into the error, never the request headers.
function describeGitlabError(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const { message, error } = body as { message?: unknown; error?: unknown };
  const raw = message ?? error;
  if (typeof raw === "string") return raw;
  if (raw !== undefined) return JSON.stringify(raw);
  return null;
}

async function gitlabRequest<T>(
  client: GitlabClient,
  method: "GET" | "POST",
  path: string,
  body?: Record<string, unknown>,
): Promise<T> {
  const doFetch = client.fetch ?? fetch;
  const response = await doFetch(`https://${client.host}/api/v4${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${client.token}`,
      Accept: "application/json",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!response.ok) {
    const detail = describeGitlabError(parsed);
    throw new GitlabApiError(
      `GitLab API ${method} ${path.split("?")[0]} failed with HTTP ${response.status}` +
        (detail ? `: ${detail}` : ""),
      response.status,
    );
  }
  return parsed as T;
}

export interface GitlabMergeRequest {
  iid: number;
  web_url: string;
  title: string;
  state: string;
  draft: boolean;
  source_branch: string;
  target_branch: string;
  sha: string | null;
  created_at: string | null;
  author_username: string | null;
  source_project_id: number | null;
  target_project_id: number | null;
}

interface RawMergeRequest {
  iid: number;
  web_url: string;
  title: string;
  state: string;
  draft?: boolean;
  work_in_progress?: boolean;
  source_branch: string;
  target_branch: string;
  sha?: string | null;
  created_at?: string | null;
  author?: { username?: string } | null;
  source_project_id?: number | null;
  target_project_id?: number | null;
}

function toMergeRequest(raw: RawMergeRequest): GitlabMergeRequest {
  return {
    iid: raw.iid,
    web_url: raw.web_url,
    title: raw.title,
    state: raw.state,
    draft: raw.draft ?? raw.work_in_progress ?? false,
    source_branch: raw.source_branch,
    target_branch: raw.target_branch,
    sha: raw.sha ?? null,
    created_at: raw.created_at ?? null,
    author_username: raw.author?.username ?? null,
    source_project_id: raw.source_project_id ?? null,
    target_project_id: raw.target_project_id ?? null,
  };
}

export async function getGitlabDefaultBranch(
  client: GitlabClient,
  projectPath: string,
): Promise<string> {
  const project = await gitlabRequest<{ default_branch?: string | null }>(
    client,
    "GET",
    projectApiPath(projectPath),
  );
  if (!project?.default_branch) {
    throw new GitlabApiError(
      `GitLab project ${projectPath} has no default branch`,
      404,
    );
  }
  return project.default_branch;
}

export async function getGitlabMergeRequest(
  client: GitlabClient,
  projectPath: string,
  iid: number,
): Promise<GitlabMergeRequest> {
  return toMergeRequest(
    await gitlabRequest<RawMergeRequest>(
      client,
      "GET",
      `${projectApiPath(projectPath)}/merge_requests/${iid}`,
    ),
  );
}

export async function findGitlabMergeRequestBySourceBranch(
  client: GitlabClient,
  projectPath: string,
  sourceBranch: string,
): Promise<GitlabMergeRequest | null> {
  const query = new URLSearchParams({
    source_branch: sourceBranch,
    order_by: "created_at",
    sort: "desc",
    per_page: "1",
  });
  query.set("state", "opened");
  const path = `${projectApiPath(projectPath)}/merge_requests`;
  const open = await gitlabRequest<RawMergeRequest[]>(
    client,
    "GET",
    `${path}?${query}`,
  );
  if (open?.[0]) return toMergeRequest(open[0]);

  query.delete("state");
  const historical = await gitlabRequest<RawMergeRequest[]>(
    client,
    "GET",
    `${path}?${query}`,
  );
  return historical?.[0] ? toMergeRequest(historical[0]) : null;
}

const DRAFT_TITLE_PREFIX = /^\s*(?:draft:|\[draft\]|\(draft\))/i;

/** GitLab has no draft flag on create. A `Draft: ` title prefix marks a draft. */
export function toDraftTitle(title: string): string {
  const trimmed = title.trim();
  return DRAFT_TITLE_PREFIX.test(trimmed) ? trimmed : `Draft: ${trimmed}`;
}

export async function createGitlabDraftMergeRequest(
  client: GitlabClient,
  projectPath: string,
  input: {
    sourceBranch: string;
    targetBranch: string;
    title: string;
    description?: string;
  },
): Promise<GitlabMergeRequest> {
  return toMergeRequest(
    await gitlabRequest<RawMergeRequest>(
      client,
      "POST",
      `${projectApiPath(projectPath)}/merge_requests`,
      {
        source_branch: input.sourceBranch,
        target_branch: input.targetBranch,
        title: toDraftTitle(input.title),
        ...(input.description ? { description: input.description } : {}),
      },
    ),
  );
}

export async function getGitlabCurrentUsername(
  client: GitlabClient,
): Promise<string | null> {
  const user = await gitlabRequest<{ username?: string }>(
    client,
    "GET",
    "/user",
  );
  return user?.username || null;
}
