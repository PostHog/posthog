import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { KnowledgeKeyApi, KnowledgeLibraryApi } from '../../generated/api.schemas'

const LIBRARIES_URL = '/api/projects/:team_id/business_knowledge/libraries/'
const KEYS_URL = '/api/projects/:team_id/business_knowledge/keys/'

const libraries: KnowledgeLibraryApi[] = [
    { id: 'library-public', name: 'Public docs', is_default: false, source_count: 12, repos: ['acme/docs'] },
    { id: 'library-team', name: 'Team handbook', is_default: true, source_count: 4, repos: [] },
]

const key: KnowledgeKeyApi = {
    id: 'key-docs',
    label: 'Help desk agent',
    mask_value: 'phs_...a1b2',
    value: null,
    created_at: '2023-01-10T09:00:00Z',
    last_used_at: '2023-01-27T16:40:00Z',
    is_limited: true,
    library_id: 'library-public',
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Business knowledge/Libraries',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28T10:00:00Z',
        featureFlags: [FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE],
        pageUrl: urls.businessKnowledgeLibraries(),
        // A scene used by one product: render it in CI, but keep no visual baseline.
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                [LIBRARIES_URL]: libraries,
                [KEYS_URL]: [
                    key,
                    { ...key, id: 'key-all', label: 'Internal agent', is_limited: false, library_id: null },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const WithLibraries: Story = {}

export const NoLibraries: Story = {
    decorators: [mswDecorator({ get: { [LIBRARIES_URL]: [], [KEYS_URL]: [] } })],
}
