// Create context for CLI that matches MCP expectations  
import { ApiClient } from './api-client.js'
import type { CLIConfig } from './config.js'

// Define Context interface to match MCP expectations
export interface Context {
  api: ApiClient
  stateManager: {
    getProjectId: () => Promise<string>
    getUserEmail: () => Promise<string>
  }
  cache: any
  env: any
  sessionManager: any
  getDistinctId: () => Promise<string>
  trackEvent: () => Promise<void>
}

export function createMCPContext(config: Required<CLIConfig>): Context {
  const apiClient = new ApiClient({
    apiToken: config.apiKey,
    baseUrl: config.host,
    clientUserAgent: 'PostHog-CLI-2.0/0.1.0'
  })

  // Create a context that matches MCP's expectations
  return {
    api: apiClient,
    stateManager: {
      getProjectId: async () => config.projectId,
      getUserEmail: async () => 'cli-user@posthog.com'
    },
    cache: {
      // Minimal cache implementation for CLI
      get: async () => null,
      set: async () => {},
      delete: async () => {},
      clear: async () => {}
    } as any,
    env: {
      // Mock environment for CLI
      POSTHOG_BASE_URL: config.host,
      NODE_ENV: 'production'
    } as any,
    sessionManager: {
      // Mock session manager
      getSessionId: async () => 'cli-session',
      getUserSession: async () => null
    } as any,
    getDistinctId: async () => 'cli-user',
    trackEvent: async () => {} // No tracking for CLI
  }
}