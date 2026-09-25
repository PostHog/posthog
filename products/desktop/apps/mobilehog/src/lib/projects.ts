import { authedFetch, getBaseUrl, refreshAccessTokenOnce } from "@/lib/api";
import { requireSession, sessionIdentity, useAuth } from "@/lib/auth";

export interface ProjectOption {
  id: number;
  name: string;
}

async function loadProject(
  projectId: number,
  signal?: AbortSignal,
): Promise<ProjectOption | null> {
  const response = await authedFetch(
    `${getBaseUrl()}/api/projects/${projectId}/`,
    { signal },
  );
  if (response.status === 403 || response.status === 404) return null;
  if (!response.ok) throw new Error("Could not load the project. Try again.");
  return response.json();
}

export async function loadProjects(
  signal: AbortSignal,
): Promise<ProjectOption[]> {
  const identity = sessionIdentity();
  const current = requireSession();
  if (current.refreshToken && current.scopedTeams === undefined) {
    await refreshAccessTokenOnce();
  }
  if (sessionIdentity() !== identity)
    throw new Error("Session changed. Open Settings again.");
  const { scopedTeams } = requireSession();
  if (scopedTeams?.length) {
    const projects = await Promise.all(
      scopedTeams.map((id) => loadProject(id, signal)),
    );
    return projects.filter(
      (project): project is ProjectOption => project !== null,
    );
  }
  const projects: ProjectOption[] = [];
  let hasNext = true;
  while (hasNext) {
    const response = await authedFetch(
      `${getBaseUrl()}/api/projects/?limit=100&offset=${projects.length}`,
      { signal },
    );
    if (!response.ok) throw new Error("Could not load projects. Try again.");
    const page = (await response.json()) as {
      results: ProjectOption[];
      next: string | null;
    };
    projects.push(...page.results);
    hasNext = !!page.next && page.results.length > 0;
  }
  return projects;
}

export async function switchProject(projectId: number): Promise<void> {
  const identity = sessionIdentity();
  const project = await loadProject(projectId);
  if (!project) throw new Error("You no longer have access to this project.");
  await useAuth.getState().selectProject(project.id, project.name, identity);
}
