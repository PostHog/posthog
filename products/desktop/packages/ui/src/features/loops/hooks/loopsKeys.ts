export const loopsKeys = {
  list: (projectId: string | null) => ["loops", "list", projectId] as const,
  detail: (projectId: string | null, loopId: string) =>
    ["loops", "detail", projectId, loopId] as const,
  runs: (projectId: string | null, loopId: string) =>
    ["loops", "runs", projectId, loopId] as const,
  preview: (projectId: string | null, loopId: string) =>
    ["loops", "preview", projectId, loopId] as const,
};
