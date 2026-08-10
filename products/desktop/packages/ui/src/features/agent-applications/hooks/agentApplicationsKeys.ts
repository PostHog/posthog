export const agentApplicationsKeys = {
  list: (projectId: number | null) =>
    ["agent-applications", "list", projectId] as const,
  detail: (projectId: number | null, idOrSlug: string) =>
    ["agent-applications", "detail", projectId, idOrSlug] as const,
  sessions: (projectId: number | null, idOrSlug: string) =>
    ["agent-applications", "sessions", projectId, idOrSlug] as const,
  session: (projectId: number | null, idOrSlug: string, sessionId: string) =>
    ["agent-applications", "session", projectId, idOrSlug, sessionId] as const,
  sessionLogs: (
    projectId: number | null,
    idOrSlug: string,
    sessionId: string,
  ) =>
    [
      "agent-applications",
      "session-logs",
      projectId,
      idOrSlug,
      sessionId,
    ] as const,
  /**
   * Shared prefix for every approval query of an agent — both the list
   * (`approvals`) and the in-chat pending-approval poll (`chatPendingApproval`)
   * live under it, so invalidating this prefix clears both at once.
   */
  approvalsPrefix: (projectId: number | null, idOrSlug: string) =>
    ["agent-applications", "approvals", projectId, idOrSlug] as const,
  approvals: (projectId: number | null, idOrSlug: string, state?: string) =>
    [
      "agent-applications",
      "approvals",
      projectId,
      idOrSlug,
      state ?? "all",
    ] as const,
  /**
   * Tight-poll cache for the in-chat pending-approval card. Lives under the
   * same "approvals" prefix that `useDecideAgentApproval` invalidates, so a
   * decide hits this hook too (clears the card optimistically).
   */
  chatPendingApproval: (
    projectId: number | null,
    idOrSlug: string,
    sessionId: string | null,
  ) =>
    [
      "agent-applications",
      "approvals",
      projectId,
      idOrSlug,
      "chat-pending",
      sessionId,
    ] as const,
  revisions: (projectId: number | null, idOrSlug: string) =>
    ["agent-applications", "revisions", projectId, idOrSlug] as const,
  /**
   * Prefix over every single-revision query (any `revisionId`) for one agent.
   * Invalidate it to refresh all `revision(...)` caches at once — derive the
   * prefix here so it can't drift from the `revision` key it must match.
   */
  revisionPrefix: (projectId: number | null, idOrSlug: string) =>
    ["agent-applications", "revision", projectId, idOrSlug] as const,
  revision: (projectId: number | null, idOrSlug: string, revisionId: string) =>
    [
      "agent-applications",
      "revision",
      projectId,
      idOrSlug,
      revisionId,
    ] as const,
  bundle: (projectId: number | null, idOrSlug: string, revisionId: string) =>
    ["agent-applications", "bundle", projectId, idOrSlug, revisionId] as const,
  envKeys: (
    projectId: number | null,
    idOrSlug: string,
    revisionId: string | null,
  ) =>
    [
      "agent-applications",
      "env-keys",
      projectId,
      idOrSlug,
      revisionId,
    ] as const,
  slackManifest: (
    projectId: number | null,
    idOrSlug: string,
    revisionId: string,
  ) =>
    [
      "agent-applications",
      "slack-manifest",
      projectId,
      idOrSlug,
      revisionId,
    ] as const,
  memoryTree: (projectId: number | null, idOrSlug: string) =>
    ["agent-applications", "memory-tree", projectId, idOrSlug] as const,
  memoryFile: (projectId: number | null, idOrSlug: string, path: string) =>
    ["agent-applications", "memory-file", projectId, idOrSlug, path] as const,
  memorySearch: (projectId: number | null, idOrSlug: string, query: string) =>
    [
      "agent-applications",
      "memory-search",
      projectId,
      idOrSlug,
      query,
    ] as const,
  memoryTables: (projectId: number | null, idOrSlug: string) =>
    ["agent-applications", "memory-tables", projectId, idOrSlug] as const,
  memoryTable: (projectId: number | null, idOrSlug: string, name: string) =>
    ["agent-applications", "memory-table", projectId, idOrSlug, name] as const,
  users: (projectId: number | null, idOrSlug: string) =>
    ["agent-applications", "users", projectId, idOrSlug] as const,
  fleetLiveSessions: (projectId: number | null) =>
    ["agent-applications", "fleet", "live-sessions", projectId] as const,
  fleetApprovals: (projectId: number | null, state?: string) =>
    [
      "agent-applications",
      "fleet",
      "approvals",
      projectId,
      state ?? "all",
    ] as const,
  /** `applicationId` is undefined for the fleet-wide board. */
  analytics: (projectId: number | null, applicationId?: string) =>
    [
      "agent-applications",
      "analytics",
      projectId,
      applicationId ?? "fleet",
    ] as const,
};
