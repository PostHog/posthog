/**
 * Product manifest for agent_stack — the operator UI for the PostHog agent platform.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'AgentStack',
    scenes: {
        AgentApplications: {
            name: 'Agent stack',
            projectBased: true,
            import: () => import('./frontend/AgentApplicationsScene'),
        },
        AgentApplication: {
            name: 'Agent application',
            projectBased: true,
            import: () => import('./frontend/AgentApplicationScene'),
        },
    },
    routes: {
        '/agents': ['AgentApplications', 'agentApplications'],
        '/agents/:slug': ['AgentApplication', 'agentApplication'],
    },
    redirects: {},
    urls: {
        agentApplications: (): string => '/agents',
        agentApplication: (slug: string): string => `/agents/${slug}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
