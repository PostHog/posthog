import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { KnowledgeKeyApi, KnowledgeLibraryApi, KnowledgeSourceApi } from '../../generated/api.schemas'

const LIBRARY_URL = '/api/projects/:team_id/business_knowledge/libraries/:id/'
const LIBRARIES_URL = '/api/projects/:team_id/business_knowledge/libraries/'
const SOURCES_URL = '/api/projects/:team_id/business_knowledge/sources/'
const KEYS_URL = '/api/projects/:team_id/business_knowledge/keys/'

const library: KnowledgeLibraryApi = {
    id: 'library-public',
    name: 'Public docs',
    is_default: false,
    source_count: 2,
    repos: ['acme/docs', 'acme/sdk-examples'],
}

function makeSource(id: string, name: string, overrides: Partial<KnowledgeSourceApi> = {}): KnowledgeSourceApi {
    return {
        id,
        team_id: 1,
        name,
        source_type: 'url',
        is_generated: false,
        status: 'ready',
        error_message: '',
        document_count: 40,
        chunk_count: 412,
        created_at: '2023-01-10T09:00:00Z',
        updated_at: '2023-01-10T09:00:00Z',
        source_url: 'https://example.com/docs',
        last_refresh_at: null,
        last_refresh_status: 'success',
        last_refresh_error: '',
        refresh_interval: '24h',
        next_refresh_at: null,
        has_unsafe_documents: false,
        embedding_status: 'completed',
        learned_from_ticket_number: null,
        learned_from_ticket_url: null,
        crawl_mode: 'sitemap',
        crawl_config: {},
        original_filename: '',
        file_content_type: '',
        file_size_bytes: null,
        always_include: false,
        library_ids: [library.id],
        cited_run_count: 0,
        last_cited_at: null,
        ...overrides,
    }
}

const sources: KnowledgeSourceApi[] = [
    makeSource('source-docs', 'Help center'),
    makeSource('source-pricing', 'Pricing FAQ', { source_type: 'text', chunk_count: 6, document_count: 1 }),
]

const key: KnowledgeKeyApi = {
    id: 'key-docs',
    label: 'Help desk agent',
    mask_value: 'phs_...a1b2',
    value: null,
    created_at: '2023-01-10T09:00:00Z',
    last_used_at: '2023-01-27T16:40:00Z',
    is_limited: true,
    library_id: library.id,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Business knowledge/Library',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28T10:00:00Z',
        featureFlags: [FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE, FEATURE_FLAGS.BUSINESS_KNOWLEDGE_MCP],
        pageUrl: urls.businessKnowledgeLibrary(library.id),
        // A scene used by one product: render it in CI, but keep no visual baseline.
        testOptions: { snapshotBrowsers: [] },
    },
    decorators: [
        mswDecorator({
            get: {
                [LIBRARY_URL]: library,
                [LIBRARIES_URL]: [library],
                [SOURCES_URL]: { count: sources.length, results: sources },
                [KEYS_URL]: [key],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const WithSourcesAndKey: Story = {}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                [LIBRARY_URL]: { ...library, source_count: 0, repos: [] },
                [LIBRARIES_URL]: [library],
                [SOURCES_URL]: { count: 0, results: [] },
                [KEYS_URL]: [],
            },
        }),
    ],
}
