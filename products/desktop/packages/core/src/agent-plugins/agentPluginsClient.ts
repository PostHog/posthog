export const AGENT_PLUGINS_CLIENT = Symbol.for(
  "posthog.core.agentPlugins.client",
);

export interface AgentPluginDiagnostic {
  severity: "warning" | "error";
  code: string;
  message: string;
  path?: string;
}

export interface AgentPluginManifest {
  $schema: string;
  name: string;
  version?: string;
  description?: string;
  author?: { name?: string; email?: string; url?: string };
  homepage?: string;
  repository?: string;
  license?: string;
  keywords?: string[];
}

export interface AgentPluginSkill {
  name: string;
  description: string;
  path: string;
}

export interface AgentPluginMcpServerSummary {
  name: string;
  type: "streamable-http" | "stdio" | "sse";
  command?: string;
  args?: string[];
  cwd?: string;
  envNames?: string[];
  approval: "not-required" | "approved" | "required";
}

export interface AgentPluginPreview {
  valid: boolean;
  sourcePath: string;
  manifest: AgentPluginManifest | null;
  skills: AgentPluginSkill[];
  mcpServers: AgentPluginMcpServerSummary[];
  diagnostics: AgentPluginDiagnostic[];
  selectionToken?: string;
}

export interface AgentPluginInstallation {
  id: string;
  sourcePath: string;
  enabled: boolean;
  manifest: AgentPluginManifest;
  skills: AgentPluginSkill[];
  mcpServers: AgentPluginMcpServerSummary[];
  diagnostics: AgentPluginDiagnostic[];
  stdioApprovalRequired: boolean;
}

export interface AgentPluginsClient {
  list(): Promise<AgentPluginInstallation[]>;
  select(): Promise<AgentPluginPreview | null>;
  register(selectionToken: string): Promise<AgentPluginInstallation>;
  setEnabled(id: string, enabled: boolean): Promise<AgentPluginInstallation>;
  approveStdio(id: string): Promise<AgentPluginInstallation>;
  unregister(id: string): Promise<void>;
}
