import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { KnowledgeKeyApi, KnowledgeLibraryApi } from '../../generated/api.schemas'
import { ConnectAgentSetting } from './ConnectAgentSetting'

const libraries: KnowledgeLibraryApi[] = [
    { id: 'library-public', name: 'Public docs', is_default: false, source_count: 12, repos: [] },
    { id: 'library-team', name: 'Team handbook', is_default: true, source_count: 4, repos: [] },
]

const keys: KnowledgeKeyApi[] = [
    {
        id: 'key-docs',
        label: 'Docs agent',
        mask_value: 'phs_...4f2a',
        value: null,
        created_at: '2026-01-10T09:00:00Z',
        last_used_at: '2026-01-14T15:00:00Z',
        is_limited: true,
        library_id: 'library-public',
    },
    {
        id: 'key-all',
        label: 'Internal agent',
        mask_value: 'phs_...91bc',
        value: null,
        created_at: '2026-01-08T09:00:00Z',
        last_used_at: null,
        is_limited: false,
        library_id: null,
    },
    {
        id: 'key-orphan',
        label: 'Old agent',
        mask_value: 'phs_...07de',
        value: null,
        created_at: '2026-01-02T09:00:00Z',
        last_used_at: null,
        is_limited: true,
        library_id: null,
    },
]

const meta: Meta<typeof ConnectAgentSetting> = {
    title: 'Scenes-App/BusinessKnowledge/ConnectAgentSetting',
    component: ConnectAgentSetting,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-01-15',
        // Used by one settings section, so the story checks that it renders and adds no visual baseline.
        testOptions: {
            snapshotBrowsers: [],
            waitForSelector: '[data-attr=business-knowledge-connect-agent-library]',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/business_knowledge/libraries/': libraries,
                '/api/projects/:team_id/business_knowledge/keys/': keys,
            },
            post: {
                '/api/projects/:team_id/business_knowledge/keys/': {
                    ...keys[0],
                    library_id: 'library-team',
                    id: 'key-new',
                    label: 'Support agent',
                    mask_value: 'phs_...c3d4',
                    value: 'phs_example',
                    last_used_at: null,
                },
            },
        }),
    ],
}

export default meta

type Story = StoryObj<typeof ConnectAgentSetting>

export const Default: Story = {}
