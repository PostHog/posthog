export interface McpUiResource {
  uri: string;
  html: string;
  csp?: Record<string, unknown>;
  permissions?: Record<string, Record<string, unknown>>;
}
