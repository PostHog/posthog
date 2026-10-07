// Local stack by default. Use your LAN IP instead of localhost on a real phone.
export const POSTHOG_HOST = "http://localhost:8010";

// Prefilled on the login screen in development builds only.
export const DEV_EMAIL = "test@posthog.com";
export const DEV_PASSWORD = "12345678";

// "owner/repo". Null uses the most recently used repository on the project.
export const DEFAULT_REPOSITORY: string | null = null;

export const DEFAULT_MODEL = "claude-opus-4-8";

// PostHog's MCP server per region; local is the services/mcp dev server.
export const MCP_HOSTS = {
  local: "http://localhost:8787/mcp",
  us: "https://mcp.posthog.com/mcp",
  eu: "https://mcp-eu.posthog.com/mcp",
} as const;
