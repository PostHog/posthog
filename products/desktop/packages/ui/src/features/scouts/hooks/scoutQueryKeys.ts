export const scoutQueryKeys = {
  configs: (projectId: number | null) =>
    ["scouts", "configs", projectId] as const,
  metadata: (projectId: number | null) =>
    ["scouts", "metadata", projectId] as const,
  runs: (projectId: number | null) => ["scouts", "runs", projectId] as const,
  skillCreators: (projectId: number | null) =>
    ["scouts", "skillCreators", projectId] as const,
  scratchpad: (projectId: number | null) =>
    ["scouts", "scratchpad", projectId] as const,
  emissions: (projectId: number | null, runIds: string[]) =>
    ["scouts", "emissions", projectId, runIds] as const,
  emissionReports: (projectId: number | null, runIds: string[]) =>
    ["scouts", "emissionReports", projectId, runIds] as const,
};
