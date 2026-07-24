import type {
  AgentMemoryFile,
  AgentMemorySearchResult,
  AgentMemoryTableHeader,
  AgentMemoryTableRows,
  AgentMemoryTreeNode,
} from "@posthog/shared/agent-platform-types";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { agentApplicationsKeys } from "./agentApplicationsKeys";

/** The agent's memory folder tree. */
export function useAgentMemoryTree(idOrSlug: string) {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  return useAuthenticatedQuery<AgentMemoryTreeNode | null>(
    agentApplicationsKeys.memoryTree(projectId, idOrSlug),
    (client) => client.getAgentMemoryTree(idOrSlug),
    { enabled: !!projectId && !!idOrSlug, staleTime: 15_000 },
  );
}

/** One memory file's header + content. Fetches only when `path` is set. */
export function useAgentMemoryFile(
  idOrSlug: string,
  path: string | null | undefined,
) {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  return useAuthenticatedQuery<AgentMemoryFile | null>(
    agentApplicationsKeys.memoryFile(projectId, idOrSlug, path ?? ""),
    (client) =>
      path ? client.readAgentMemoryFile(idOrSlug, path) : Promise.resolve(null),
    { enabled: !!projectId && !!idOrSlug && !!path, staleTime: 15_000 },
  );
}

/** BM25 search. Fetches only when `query` is non-empty. */
export function useAgentMemorySearch(idOrSlug: string, query: string) {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const q = query.trim();
  return useAuthenticatedQuery<AgentMemorySearchResult[]>(
    agentApplicationsKeys.memorySearch(projectId, idOrSlug, q),
    (client) => client.searchAgentMemory(idOrSlug, q, 50),
    { enabled: !!projectId && !!idOrSlug && q.length > 0, staleTime: 10_000 },
  );
}

/** The agent's memory tables. */
export function useAgentMemoryTables(idOrSlug: string) {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  return useAuthenticatedQuery<AgentMemoryTableHeader[]>(
    agentApplicationsKeys.memoryTables(projectId, idOrSlug),
    (client) => client.listAgentMemoryTables(idOrSlug),
    { enabled: !!projectId && !!idOrSlug, staleTime: 15_000 },
  );
}

/** Rows from one memory table. Fetches only when `name` is set. */
export function useAgentMemoryTable(
  idOrSlug: string,
  name: string | null | undefined,
) {
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  return useAuthenticatedQuery<AgentMemoryTableRows | null>(
    agentApplicationsKeys.memoryTable(projectId, idOrSlug, name ?? ""),
    (client) =>
      name
        ? client.readAgentMemoryTable(idOrSlug, name, 100)
        : Promise.resolve(null),
    { enabled: !!projectId && !!idOrSlug && !!name, staleTime: 15_000 },
  );
}
