import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Cloud agents',
    urls: {
        cloudAgents: (): string => '/cloud-agents',
        cloudAgentRun: (id: string): string => `/cloud-agents/runs/${id}`,
        cloudAgentPresets: (): string => '/cloud-agents/presets',
        cloudAgentPreset: (id: string | 'new'): string => `/cloud-agents/presets/${id}`,
        cloudAgentsUsage: (): string => '/cloud-agents/usage',
        cloudAgentsSettings: (): string => '/cloud-agents/settings',
    },
    scenes: {
        CloudAgents: {
            name: 'Cloud agents',
            description:
                'Send a prompt and a repository. A coding agent works in a cloud sandbox and opens a pull request.',
            docsHref: 'https://posthog.com/docs/cloud-agents/api',
            import: () => import('./frontend/scenes/CloudAgentsRunsScene'),
            projectBased: true,
            layout: 'app-container',
            iconType: 'cloud_agent',
        },
        CloudAgentRun: {
            name: 'Cloud agent run',
            import: () => import('./frontend/scenes/CloudAgentRunScene'),
            projectBased: true,
            layout: 'app-container',
            iconType: 'cloud_agent',
        },
        CloudAgentPresets: {
            name: 'Cloud agent presets',
            description:
                'Send a prompt and a repository. A coding agent works in a cloud sandbox and opens a pull request.',
            import: () => import('./frontend/scenes/CloudAgentPresetsScene'),
            projectBased: true,
            layout: 'app-container',
            iconType: 'cloud_agent',
        },
        CloudAgentPreset: {
            name: 'Cloud agent preset',
            import: () => import('./frontend/scenes/CloudAgentPresetScene'),
            projectBased: true,
            layout: 'app-container',
            iconType: 'cloud_agent',
        },
        CloudAgentsUsage: {
            name: 'Cloud agents usage',
            description:
                'Send a prompt and a repository. A coding agent works in a cloud sandbox and opens a pull request.',
            import: () => import('./frontend/scenes/CloudAgentsUsageScene'),
            projectBased: true,
            layout: 'app-container',
            iconType: 'cloud_agent',
        },
        CloudAgentsSettings: {
            name: 'Cloud agents settings',
            description:
                'Send a prompt and a repository. A coding agent works in a cloud sandbox and opens a pull request.',
            import: () => import('./frontend/scenes/CloudAgentsSettingsScene'),
            projectBased: true,
            layout: 'app-container',
            iconType: 'cloud_agent',
        },
    },
    routes: {
        '/cloud-agents': ['CloudAgents', 'cloudAgents'],
        '/cloud-agents/presets': ['CloudAgentPresets', 'cloudAgentPresets'],
        '/cloud-agents/presets/:id': ['CloudAgentPreset', 'cloudAgentPreset'],
        '/cloud-agents/usage': ['CloudAgentsUsage', 'cloudAgentsUsage'],
        '/cloud-agents/settings': ['CloudAgentsSettings', 'cloudAgentsSettings'],
        '/cloud-agents/runs/:id': ['CloudAgentRun', 'cloudAgentRun'],
    },
    redirects: {
        '/cloud-agents/runs': (): string => urls.cloudAgents(),
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Cloud agents',
            intents: [ProductKey.CLOUD_AGENTS],
            href: urls.cloudAgents(),
            type: 'cloud_agent',
            category: ProductItemCategory.UNRELEASED,
            flag: FEATURE_FLAGS.CLOUD_AGENTS,
            iconType: 'cloud_agent',
            iconColor: ['var(--color-product-tasks-light)', 'var(--color-product-tasks-dark)'],
            sceneKey: 'CloudAgents',
            sceneKeys: [
                'CloudAgents',
                'CloudAgentRun',
                'CloudAgentPresets',
                'CloudAgentPreset',
                'CloudAgentsUsage',
                'CloudAgentsSettings',
            ],
        },
    ],
}
