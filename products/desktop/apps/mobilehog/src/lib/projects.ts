import { useQuery } from "@tanstack/react-query";
import { authedFetch, getBaseUrl, refreshAccessTokenOnce } from "@/lib/api";
import { requireSession, useAuth } from "@/lib/auth";

export interface ProjectOption {
  id: number;
  name: string;
}

async function loadProject(projectId: number): Promise<ProjectOption | null> {
  const response = await authedFetch(
    `${getBaseUrl()}/api/projects/${projectId}/`,
  );
  if (response.status === 403 || response.status === 404) return null;
  if (!response.ok) throw new Error("Could not load the project. Try again.");
  return response.json();
}

async function loadProjects(): Promise<ProjectOption[]> {
  // Sessions from before scoped teams were stored learn them on the next refresh.
  if (requireSession().refreshToken && !requireSession().scopedTeams) {
    await refreshAccessTokenOnce();
  }
  const { scopedTeams } = requireSession();
  // A scoped token can reach projects outside the current organization.
  if (scopedTeams?.length) {
    const projects = await Promise.all(scopedTeams.map(loadProject));
    return projects.filter((project): project is ProjectOption => !!project);
  }
  const projects: ProjectOption[] = [];
  let hasNext = true;
  while (hasNext) {
    const response = await authedFetch(
      `${getBaseUrl()}/api/projects/?limit=100&offset=${projects.length}`,
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

export function useProjects() {
  const session = useAuth((s) => s.session);
  return useQuery({
    queryKey: ["projects", session?.host, session?.userId],
    queryFn: loadProjects,
    enabled: !!session,
    staleTime: 5 * 60_000,
  });
}
