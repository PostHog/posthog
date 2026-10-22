import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { userEvent } from 'storybook/test'

import type { KnowledgeSearchResultApi, PlaygroundChatApi, PlaygroundChatListApi } from '../../generated/api.schemas'

const listedChat: PlaygroundChatListApi = {
    id: 'chat-1',
    title: 'Can customers get a refund after 30 days?',
    created_at: '2023-01-28T09:00:00Z',
    updated_at: '2023-01-28T09:05:00Z',
    has_open_turn: true,
}

const olderChat: PlaygroundChatListApi = {
    id: 'chat-2',
    title: 'Which plans include priority support?',
    created_at: '2023-01-20T09:00:00Z',
    updated_at: '2023-01-20T09:00:00Z',
    has_open_turn: true,
}

const chat: PlaygroundChatApi = {
    ...listedChat,
    turns: [
        {
            id: 'turn-1',
            question: 'Can customers get a refund after 30 days?',
            task_id: 'task-1',
            position: 0,
            error: null,
            run: {
                task_id: 'task-1',
                run_id: 'run-1',
                status: 'completed',
                reply: 'Refunds are available within **30 days** of purchase. After that, a manager has to approve an exception.',
                sources: [{ ref: 'Refund policy', excerpt: 'Refunds after 30 days need manager approval.' }],
                searches: [
                    {
                        tool: 'business-knowledge-documents-search',
                        input: 'call business-knowledge-documents-search {"query": "refund after 30 days"}',
                    },
                    {
                        tool: 'business-knowledge-document-window-retrieve',
                        input: 'call business-knowledge-document-window-retrieve {"id": "doc-1", "around_ordinal": 3}',
                    },
                ],
                error: null,
                docs_search_called: false,
            },
        },
        {
            id: 'turn-2',
            question: 'Who approves the exception?',
            task_id: 'task-2',
            position: 1,
            error: null,
            run: {
                task_id: 'task-2',
                run_id: 'run-2',
                status: 'running',
                reply: null,
                sources: [],
                searches: [],
                error: null,
                docs_search_called: false,
            },
        },
    ],
}

const searchResults: KnowledgeSearchResultApi[] = [
    {
        chunk_id: 'chunk-1',
        document_id: 'doc-1',
        ordinal: 3,
        source_id: 'source-1',
        source_name: 'Refund policy',
        source_type: 'url',
        document_title: 'Refunds and cancellations',
        heading_path: 'Billing > Refunds',
        content: [
            'Refunds are available within 30 days of purchase for annual and monthly plans.',
            'After 30 days, a support manager has to approve an exception. Open a ticket with the order number and the reason for the request.',
            'Approved exceptions are refunded to the original payment method within 5 to 10 business days.',
            'Usage-based charges for the current billing period are not refundable.',
        ].join('\n\n'),
        is_generated: false,
        url: 'https://example.com/help/refunds',
    },
    {
        chunk_id: 'chunk-2',
        document_id: 'doc-2',
        ordinal: 0,
        source_id: 'source-2',
        source_name: 'Support policies',
        source_type: 'text',
        document_title: 'Support policies',
        heading_path: '',
        content: 'Priority support is included on the Enterprise plan.',
        is_generated: false,
        url: '',
    },
]

// The fixtures show answers that are still running, so their spinners never hide.
const LIST_SELECTOR = '[data-attr="business-knowledge-playground-open-chat"]'
const SAVED_CHAT_SELECTORS = [LIST_SELECTOR, 'text=Refund policy']

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Business knowledge/Playground',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28T10:00:00Z',
        featureFlags: [FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE],
        pageUrl: urls.businessKnowledgePlayground(chat.id),
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: SAVED_CHAT_SELECTORS },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/business_knowledge/playground/chats/': [listedChat, olderChat],
                '/api/projects/:team_id/business_knowledge/playground/chats/:chatId/': chat,
                '/api/projects/:team_id/business_knowledge/documents/search/': searchResults,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const SavedChat: Story = {}

export const NewChat: Story = {
    parameters: {
        pageUrl: urls.businessKnowledgePlayground(),
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: LIST_SELECTOR },
    },
}

export const SearchResults: Story = {
    parameters: {
        pageUrl: urls.businessKnowledgePlayground(),
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: 'text=Refunds and cancellations' },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await waitFor(() => {
            const modeSearch = canvasElement.querySelector<HTMLElement>(
                '[data-attr="business-knowledge-playground-mode-search"]'
            )
            if (!modeSearch) {
                throw new Error('The mode switcher must render')
            }
            modeSearch.click()
        })
        await userEvent.type(await canvas.findByPlaceholderText('Search business knowledge'), 'refund{Enter}')
    },
}

export const ChatCitations: Story = {
    parameters: {
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: 'text=Refunds and cancellations' },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByText('Looked through business knowledge'))
        await userEvent.click(await canvas.findByText('Searched business knowledge'))
    },
}

export const NarrowScene: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: SAVED_CHAT_SELECTORS,
            viewport: { width: 560, height: 900 },
        },
    },
}
