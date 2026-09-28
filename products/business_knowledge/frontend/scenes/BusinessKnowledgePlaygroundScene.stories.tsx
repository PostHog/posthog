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
}

const olderChat: PlaygroundChatListApi = {
    id: 'chat-2',
    title: 'Which plans include priority support?',
    created_at: '2023-01-20T09:00:00Z',
    updated_at: '2023-01-20T09:00:00Z',
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

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Business knowledge/Playground',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28T10:00:00Z',
        featureFlags: [FEATURE_FLAGS.PRODUCT_BUSINESS_KNOWLEDGE],
        pageUrl: urls.businessKnowledgePlayground(chat.id),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/business_knowledge/playground/chats/': [listedChat, olderChat],
                '/api/projects/:team_id/business_knowledge/playground/chats/:chatId/': chat,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const SavedChat: Story = {}

export const NewChat: Story = {
    parameters: { pageUrl: urls.businessKnowledgePlayground() },
}

export const NarrowScene: Story = {
    parameters: { testOptions: { viewport: { width: 560, height: 900 } } },
}
