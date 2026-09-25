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

jest.mock('../components/BusinessKnowledgeTabs', () => ({
    BusinessKnowledgeTabs: (): null => null,
}))

const playgroundValues = {
    question: '',
    asking: false,
    askDisabled: true,
    askError: null,
    chatHasOpenTurn: false,
    chatError: null,
    chatLoading: false,
    chatId: 'chat-1',
    chatsLoading: false,
    chats: [
        {
            id: 'chat-1',
            title: 'Can I get a refund?',
            created_at: '2026-09-25T00:00:00Z',
            updated_at: '2026-09-25T00:00:00Z',
        },
    ],
    chat: {
        id: 'chat-1',
        title: 'Can I get a refund?',
        created_at: '2026-09-25T00:00:00Z',
        updated_at: '2026-09-25T00:00:00Z',
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
                    reply: 'Yes, within 30 days.',
                    sources: [{ ref: 'Refunds', excerpt: 'Refunds need approval.' }],
                    searches: [{ tool: 'business-knowledge-documents-search', input: 'refunds' }],
                    error: null,
                    docs_search_called: false,
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
        })
    })

    afterEach(() => {
        cleanup()
    })

    it.each([520, 900] as const)('renders the list and answer at %ipx', (width) => {
        render(
            <div className={width === 520 ? 'w-[520px]' : 'w-[900px]'}>
                <BusinessKnowledgePlaygroundScene />
            </div>
        )

        expect(screen.getByText('New chat')).toBeInTheDocument()
        expect(screen.getAllByText('Can I get a refund?').length).toBeGreaterThanOrEqual(2)
        expect(screen.getByText('Yes, within 30 days.')).toBeInTheDocument()
        expect(screen.getByText(/Refunds need approval/)).toBeInTheDocument()
        expect(document.querySelector('[class*="@container"]')?.className).toContain('flex-col')
        expect(document.querySelector('[class*="@container"]')?.className).toContain('@min-[32.5625rem]:flex-row')
        expect(document.querySelector('form.max-w-180')).toBeTruthy()
        expect(document.querySelector('form .border-primary')).toBeTruthy()
    })
})
