export const loopsKeys = {
  hogFlowList: (projectId: string | null) =>
    ["loops", "hog-flows", "list", projectId] as const,
  hogFlow: (projectId: string | null, loopId: string) =>
    ["loops", "hog-flows", "detail", projectId, loopId] as const,
  hogFlowRuns: (projectId: string | null, loopId: string) =>
    ["loops", "hog-flows", "runs", projectId, loopId] as const,
};
