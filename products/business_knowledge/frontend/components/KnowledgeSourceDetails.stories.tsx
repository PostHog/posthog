import type { Meta, StoryObj } from '@storybook/react'

import type { KnowledgeSource } from '../scenes/businessKnowledgeLogic'
import { KnowledgeSourceDetails } from './KnowledgeSourceDetails'

const meta: Meta<typeof KnowledgeSourceDetails> = {
    title: 'Scenes-App/BusinessKnowledge/KnowledgeSourceDetails',
    component: KnowledgeSourceDetails,
    parameters: { layout: 'padded', viewMode: 'story' },
    args: {
        isRefreshing: false,
        isDeleting: false,
        onRefresh: () => undefined,
        onDelete: () => undefined,
    },
    decorators: [
        (Story) => (
            <div className="w-80">
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof KnowledgeSourceDetails>

function makeSource(overrides: Partial<KnowledgeSource> = {}): KnowledgeSource {
    return {
        id: '11111111-1111-1111-1111-111111111111',
        team_id: 1,
        name: 'Refund policy',
        source_type: 'text',
        is_generated: false,
        status: 'ready',
        error_message: '',
        document_count: 1,
        chunk_count: 3,
        created_at: '2026-09-01T12:00:00Z',
        updated_at: '2026-09-02T12:00:00Z',
        source_url: '',
        last_refresh_at: null,
        last_refresh_status: 'success',
        last_refresh_error: '',
        refresh_interval: 'manual',
        next_refresh_at: null,
        has_unsafe_documents: false,
        embedding_status: 'completed',
        learned_from_ticket_number: null,
        learned_from_ticket_url: null,
        crawl_mode: 'single',
        crawl_config: {},
        original_filename: '',
        file_content_type: '',
        file_size_bytes: null,
        always_include: false,
        ...overrides,
    }
}

export const Text: Story = {
    args: { source: makeSource() },
}

export const Url: Story = {
    args: {
        source: makeSource({
            source_type: 'url',
            source_url: 'https://docs.example.com',
            document_count: 12,
            chunk_count: 48,
            last_refresh_at: '2026-09-20T08:00:00Z',
            next_refresh_at: '2026-09-27T08:00:00Z',
            refresh_interval: '7d',
        }),
    },
}

export const File: Story = {
    args: {
        source: makeSource({
            source_type: 'file',
            original_filename: 'refund-policy.pdf',
            file_content_type: 'application/pdf',
            file_size_bytes: 248320,
        }),
    },
}

export const Learned: Story = {
    args: {
        source: makeSource({
            is_generated: true,
            learned_from_ticket_number: 42,
            learned_from_ticket_url: 'https://us.posthog.com/project/1/support/tickets/42',
        }),
    },
}
