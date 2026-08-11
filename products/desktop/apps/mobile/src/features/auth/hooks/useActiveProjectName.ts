import { useAuthStore } from "../stores/authStore";
import { useProjectsQuery } from "./useProjectsQuery";

/**
 * Display name of the active project, so screens can make it apparent which
 * PostHog project the data belongs to. Falls back to `Project N` until the
 * name lookup resolves, and null when unauthenticated.
 */
export function useActiveProjectName(): string | null {
  const projectId = useAuthStore((s) => s.projectId);
  const { data: projects } = useProjectsQuery();
  if (projectId == null) return null;
  return (
    projects?.find((p) => p.id === projectId)?.name ?? `Project ${projectId}`
  );
}
