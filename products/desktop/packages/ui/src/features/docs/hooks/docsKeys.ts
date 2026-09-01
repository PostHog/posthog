export const docsKeys = {
  list: (projectId: string | null, channelId: string) =>
    ["docs", "list", projectId, channelId] as const,
  detail: (projectId: string | null, docId: string) =>
    ["docs", "detail", projectId, docId] as const,
  discussions: (projectId: string | null, docId: string) =>
    ["docs", "discussions", projectId, docId] as const,
  home: (projectId: string | null, channelId: string) =>
    ["docs", "home", projectId, channelId] as const,
};
