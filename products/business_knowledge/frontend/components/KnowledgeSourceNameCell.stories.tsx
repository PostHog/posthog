import type { Meta, StoryObj } from '@storybook/react'

import { KnowledgeSource } from '../scenes/businessKnowledgeLogic'
import { KnowledgeSourceNameCell } from './KnowledgeSourceNameCell'

const meta: Meta<typeof KnowledgeSourceNameCell> = {
    title: 'Scenes-App/BusinessKnowledge/KnowledgeSourceNameCell',
    component: KnowledgeSourceNameCell,
    parameters: { layout: 'padded', viewMode: 'story' },
}

export default meta

type Story = StoryObj<typeof KnowledgeSourceNameCell>

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
        updated_at: '2026-09-01T12:00:00Z',
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

export const UserText: Story = {
    args: {
        source: makeSource(),
    },
}

export const LearnedFromTicket: Story = {
    args: {
        source: makeSource({
            is_generated: true,
            learned_from_ticket_number: 42,
            learned_from_ticket_url: 'https://us.posthog.com/project/1/support/tickets/42',
        }),
    },
}

export const LearnedLongName: Story = {
    args: {
        source: makeSource({
            name: 'Refunds for annual plans billed through the customer portal after a failed payment retry',
            is_generated: true,
            learned_from_ticket_number: 1088,
            learned_from_ticket_url: 'https://us.posthog.com/project/1/support/tickets/1088',
        }),
    },
    decorators: [
        (Story) => (
            <div className="w-[320px]">
                <Story />
            </div>
        ),
    ],
}
