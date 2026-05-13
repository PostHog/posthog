// Create context for CLI that matches MCP expectations  
import { ApiClient } from './api-client.js'
import type { CLIConfig } from './config.js'

export type AuthenticatedConfig = CLIConfig & {
  host: string
  projectId: string
}

// Define Context interface to match MCP expectations
export interface Context {
  api: ApiClient
  stateManager: {
    getProjectId: () => Promise<string>
    getUserEmail: () => Promise<string>
    getUser: () => Promise<any>
    getApiKey: () => Promise<any>
    getCurrentProject: () => Promise<any>
    getCurrentOrganization: () => Promise<any>
    getAiConsentGiven: () => Promise<boolean | undefined>
    getGroupTypes: () => Promise<any[]>
    setProjectId: (id: string) => Promise<void>
    setOrgId: (id: string) => Promise<void>
  }
  cache: any
  env: any
  sessionManager: any
  getDistinctId: () => Promise<string>
  trackEvent: (event: any, properties?: Record<string, unknown>) => Promise<void>
}

export function createMCPContext(config: AuthenticatedConfig): Context {
  const apiToken = config.accessToken || config.apiKey
  if (!apiToken) {
    throw new Error('Missing PostHog API key or OAuth access token')
  }

  const apiClient = new ApiClient({
    apiToken,
    baseUrl: config.host,
    clientUserAgent: 'PostHog-CLI-2.0/0.1.0'
  })

  // Create a context that matches MCP's expectations
  return {
    api: apiClient,
    stateManager: {
      getProjectId: async () => config.projectId,
      getUserEmail: async () => 'cli-user@posthog.com',
      getUser: async () => ({ email: 'cli-user@posthog.com', id: 1 }),
      getApiKey: async () => ({ scopes: ['read', 'write'] }),
      getCurrentProject: async () => ({ id: config.projectId, name: 'CLI Project' }),
      getCurrentOrganization: async () => ({ id: 'cli-org', name: 'CLI Organization' }),
      getAiConsentGiven: async () => true,
      getGroupTypes: async () => [],
      setProjectId: async (id: string) => {
        // No-op for CLI
      },
      setOrgId: async (id: string) => {
        // No-op for CLI
      }
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