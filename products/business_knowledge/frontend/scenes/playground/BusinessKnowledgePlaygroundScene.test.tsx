import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import { type ReactNode } from 'react'

import { BusinessKnowledgePlaygroundScene } from './BusinessKnowledgePlaygroundScene'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: (): boolean => true,
}))

jest.mock('~/layout/scenes/components/SceneContent', () => ({
    SceneContent: ({ children }: { children: ReactNode }): JSX.Element => <>{children}</>,
}))

jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitleSection: (): null => null,
}))

jest.mock('../../components/BusinessKnowledgeTabs/BusinessKnowledgeTabs', () => ({
    BusinessKnowledgeTabs: (): null => null,
}))

const listedChat = {
    id: 'chat-1',
    title: 'Can I get a refund?',
    created_at: '2026-09-25T00:00:00Z',
    updated_at: '2026-09-25T00:00:00Z',
    has_open_turn: false,
}

const playgroundValues = {
    question: '',
    pendingQuestion: null,
    asking: false,
    askDisabled: true,
    askBlockedReason: null,
    askError: null,
    chatHasOpenTurn: false,
    chatError: null,
    chatLoading: false,
    chatId: 'chat-1',
    chatSearch: '',
    chatsLoading: false,
    chats: [listedChat],
    chatGroups: [{ label: 'Today', chats: [listedChat] }],
    deletingChatId: null,
    chat: {
        id: 'chat-1',
        title: 'Can I get a refund?',
        created_at: '2026-09-25T00:00:00Z',
        updated_at: '2026-09-25T00:00:00Z',
        has_open_turn: false,
        turns: [
            {
                id: 'turn-1',
                question: 'Can I get a refund?',
                task_id: 'task-1',
                position: 0,
                error: null,
                run: {
                    task_id: 'task-1',
                    run_id: 'run-1',
                    status: 'completed',
                    reply: '**Yes**, within 30 days.',
                    sources: [{ ref: 'Refunds', excerpt: 'Refunds need approval.' }],
                    searches: [
                        {
                            tool: 'business-knowledge-documents-search',
                            input: 'call business-knowledge-documents-search {"query": "refund window"}',
                        },
                    ],
                    error: null,
                    docs_search_called: true,
                },
            },
        ],
    },
}

describe('BusinessKnowledgePlaygroundScene', () => {
    beforeEach(() => {
        jest.mocked(useValues).mockReturnValue(playgroundValues)
        jest.mocked(useActions).mockReturnValue({
            setQuestion: jest.fn(),
            ask: jest.fn(),
            newChat: jest.fn(),
            deleteChat: jest.fn(),
            setChatSearch: jest.fn(),
        })
    })

    afterEach(() => {
        cleanup()
    })

    it('renders the chat with the shared message and composer primitives', () => {
        render(<BusinessKnowledgePlaygroundScene />)

        expect(document.querySelector('[data-attr="business-knowledge-playground-new-chat"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="business-knowledge-playground-open-chat"]')).toHaveTextContent(
            'Can I get a refund?'
        )
        expect(screen.getByText(/Refunds need approval/)).toBeInTheDocument()
        expect(document.querySelector('[data-message-type="human"]')).toHaveTextContent('Can I get a refund?')
        expect(document.querySelector('[data-message-type="ai"] [data-testid="react-markdown"]')).toHaveTextContent(
            '**Yes**, within 30 days.'
        )
        expect(screen.getByText('Searched business knowledge')).toBeInTheDocument()
        expect(screen.getByText('refund window')).toBeInTheDocument()
        expect(screen.queryByText(/call business-knowledge-documents-search/)).not.toBeInTheDocument()
        expect(document.querySelectorAll('[data-message-type="ai"]')[1]).toHaveTextContent(
            /searched PostHog documentation/
        )
        expect(document.querySelector('[data-slot="composer-root"]')).toBeInTheDocument()
        expect(document.querySelector('[data-slot="composer-frame"]')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="business-knowledge-playground-ask"]')).toBeInTheDocument()
    })
})
