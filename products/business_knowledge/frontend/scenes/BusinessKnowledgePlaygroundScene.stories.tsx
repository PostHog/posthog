import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { PlaygroundChatApi, PlaygroundChatListApi } from '../generated/api.schemas'

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
                '/api/projects/:team_id/business_knowledge/playground/chats/': {
                    count: 3,
                    next: '/api/projects/1/business_knowledge/playground/chats/?offset=2',
                    previous: null,
                    results: [listedChat, olderChat],
                },
                '/api/projects/:team_id/business_knowledge/playground/chats/:chatId/': chat,
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

export const NarrowScene: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: SAVED_CHAT_SELECTORS,
            viewport: { width: 560, height: 900 },
        },
    },
}
