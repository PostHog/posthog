export const loopsKeys = {
  list: (projectId: string | null) => ["loops", "list", projectId] as const,
  detail: (projectId: string | null, loopId: string) =>
    ["loops", "detail", projectId, loopId] as const,
  runs: (projectId: string | null, loopId: string) =>
    ["loops", "runs", projectId, loopId] as const,
  preview: (projectId: string | null, loopId: string) =>
    ["loops", "preview", projectId, loopId] as const,
  // Workflow-backed loops cache under their own keys: the raw shapes differ
  // from the loops API, so a flag flip must not read one backend's cache as
  // the other's.
  hogFlowList: (projectId: string | null) =>
    ["loops", "hog-flows", "list", projectId] as const,
  hogFlow: (projectId: string | null, loopId: string) =>
    ["loops", "hog-flows", "detail", projectId, loopId] as const,
  hogFlowRuns: (projectId: string | null, loopId: string) =>
    ["loops", "hog-flows", "runs", projectId, loopId] as const,
};
