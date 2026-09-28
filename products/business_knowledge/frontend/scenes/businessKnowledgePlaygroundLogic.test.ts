import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { askPlaygroundChat, createPlaygroundChat, getPlaygroundChat, listPlaygroundChats } from '../api'
import type { PlaygroundChatApi, PlaygroundChatListApi, SandboxRunApi } from '../generated/api.schemas'
import { businessKnowledgePlaygroundLogic } from './businessKnowledgePlaygroundLogic'

jest.mock('../api', () => ({
    listPlaygroundChats: jest.fn(),
    createPlaygroundChat: jest.fn(),
    getPlaygroundChat: jest.fn(),
    askPlaygroundChat: jest.fn(),
    deletePlaygroundChat: jest.fn(),
}))

const mockedList = listPlaygroundChats as jest.MockedFunction<typeof listPlaygroundChats>
const mockedCreate = createPlaygroundChat as jest.MockedFunction<typeof createPlaygroundChat>
const mockedGet = getPlaygroundChat as jest.MockedFunction<typeof getPlaygroundChat>
const mockedAsk = askPlaygroundChat as jest.MockedFunction<typeof askPlaygroundChat>

function run(status: SandboxRunApi['status'], extra: Partial<SandboxRunApi> = {}): SandboxRunApi {
    return {
        task_id: 'task-1',
        run_id: 'run-1',
        status,
        reply: status === 'completed' ? 'Yes, within 30 days.' : null,
        sources: [],
        searches: [],
        error: status === 'running' || status === 'completed' ? null : 'The answer stopped.',
        docs_search_called: false,
        ...extra,
    }
}

function chat(status: SandboxRunApi['status'], extra: Partial<PlaygroundChatApi> = {}): PlaygroundChatApi {
    return {
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
                run: run(status),
                error: null,
            },
        ],
        ...extra,
    }
}

const emptyChat: PlaygroundChatApi = {
    id: 'chat-1',
    title: '',
    created_at: '2026-09-25T00:00:00Z',
    updated_at: '2026-09-25T00:00:00Z',
    turns: [],
}

const listed: PlaygroundChatListApi = {
    id: 'chat-1',
    title: 'Can I get a refund?',
    created_at: '2026-09-25T00:00:00Z',
    updated_at: '2026-09-25T00:00:00Z',
}

describe('businessKnowledgePlaygroundLogic', () => {
    let logic: ReturnType<typeof businessKnowledgePlaygroundLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockedList.mockResolvedValue([])
        logic = businessKnowledgePlaygroundLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('opens a saved chat from the URL', async () => {
        mockedGet.mockResolvedValue(chat('completed'))
        mockedList.mockResolvedValue([listed])
        router.actions.push(urls.businessKnowledgePlayground('chat-1'))
        await expectLogic(logic).toDispatchActions(['chatLoaded'])
        expect(logic.values.chatId).toBe('chat-1')
        expect(logic.values.chat?.turns[0]?.run?.status).toBe('completed')
        expect(logic.values.askDisabled).toBe(true)
    })

    it('clears the thread when starting a new chat', async () => {
        mockedGet.mockResolvedValue(chat('completed'))
        router.actions.push(urls.businessKnowledgePlayground('chat-1'))
        await expectLogic(logic).toDispatchActions(['chatLoaded'])
        await expectLogic(logic, () => {
            logic.actions.newChat()
        }).toDispatchActions(['openChat'])
        expect(router.values.location.pathname).toBe(urls.currentProject(urls.businessKnowledgePlayground()))
        expect(logic.values.chatId).toBeNull()
        expect(logic.values.chat).toBeNull()
        expect(logic.values.askDisabled).toBe(true)
    })

    it('updates the URL after the first question', async () => {
        mockedCreate.mockResolvedValue(emptyChat)
        mockedAsk.mockResolvedValue(chat('running'))
        mockedGet.mockResolvedValue(chat('running'))
        logic.actions.setQuestion('Can I get a refund?')
        await expectLogic(logic, () => {
            logic.actions.ask()
        }).toDispatchActions(['chatLoaded'])
        expect(router.values.location.pathname).toBe(urls.currentProject(urls.businessKnowledgePlayground('chat-1')))
        expect(logic.values.chatId).toBe('chat-1')
        expect(mockedCreate).toHaveBeenCalledTimes(1)
        expect(mockedAsk).toHaveBeenCalledWith('chat-1', 'Can I get a refund?')
    })

    it('keeps Ask disabled through the request and every running poll', async () => {
        let release: (value: Awaited<ReturnType<typeof askPlaygroundChat>>) => void = () => {}
        mockedAsk.mockReturnValue(
            new Promise((resolve) => {
                release = resolve
            })
        )
        mockedGet.mockResolvedValue(chat('running'))

        logic.actions.setChatId('chat-1')
        logic.actions.setQuestion('Can I get a refund?')
        void logic.actions.ask()
        await expectLogic(logic).toDispatchActions(['setAsking'])
        expect(logic.values.asking).toBe(true)
        expect(logic.values.askDisabled).toBe(true)
        expect(logic.values.pendingQuestion).toBe('Can I get a refund?')
        expect(logic.values.question).toBe('')

        logic.actions.ask()
        expect(mockedAsk).toHaveBeenCalledTimes(1)

        release(chat('running'))
        await expectLogic(logic).toMatchValues({ asking: true, askDisabled: true })

        await expectLogic(logic).toDispatchActions(['chatLoaded'])
        expect(logic.values.pendingQuestion).toBeNull()
        expect(logic.values.asking).toBe(true)
        expect(logic.values.chatHasOpenTurn).toBe(true)
    })

    it('does not replace the selected chat when an earlier ask finishes', async () => {
        let release: (value: Awaited<ReturnType<typeof askPlaygroundChat>>) => void = () => {}
        mockedAsk.mockReturnValue(
            new Promise((resolve) => {
                release = resolve
            })
        )
        const otherChat = chat('completed', { id: 'chat-2', title: 'Where is the policy?' })
        mockedGet.mockResolvedValue(otherChat)

        logic.actions.setChatId('chat-1')
        logic.actions.setQuestion('Can I get a refund?')
        void logic.actions.ask()
        await expectLogic(logic).toDispatchActions(['setAsking'])

        logic.actions.openChat('chat-2')
        await expectLogic(logic).toDispatchActions(['chatLoaded'])
        release(chat('completed'))
        await expectLogic(logic).delay(0)

        expect(logic.values.chatId).toBe('chat-2')
        expect(logic.values.chat).toEqual(otherChat)
    })

    it.each([
        ['completed', chat('completed')],
        ['failed', chat('failed')],
        ['cancelled', chat('cancelled')],
    ] as const)('stops polling and re-enables Ask when the run is %s', async (_name, payload) => {
        mockedAsk.mockResolvedValue(payload)
        mockedGet.mockResolvedValue(payload)
        logic.actions.setChatId('chat-1')
        logic.actions.setQuestion('Can I get a refund?')
        await expectLogic(logic, () => {
            logic.actions.ask()
        }).toDispatchActions(['chatLoaded'])
        expect(logic.values.asking).toBe(false)
        expect(logic.values.askDisabled).toBe(true)
        expect(logic.values.question).toBe('')
        expect(logic.values.chat?.turns[0]?.run?.status).toBe(payload.turns[0].run?.status)
    })

    it('shows a retry error when the request or the poll fails', async () => {
        mockedAsk.mockRejectedValue(
            new ApiError('invalid', 403, undefined, {
                detail: 'Enable AI data processing before asking another question.',
            })
        )
        logic.actions.setChatId('chat-1')
        logic.actions.setQuestion('Can I get a refund?')
        await expectLogic(logic, () => {
            logic.actions.ask()
        }).toDispatchActions(['setAskError'])
        expect(logic.values.asking).toBe(false)
        expect(logic.values.askError).toBe('Enable AI data processing before asking another question.')
        expect(logic.values.pendingQuestion).toBeNull()
        expect(logic.values.question).toBe('Can I get a refund?')

        mockedCreate.mockResolvedValue(emptyChat)
        mockedAsk.mockResolvedValue(chat('running'))
        mockedGet.mockRejectedValue(new Error('network'))
        logic.actions.setChatId('chat-2')
        logic.actions.setQuestion('Where is the policy?')
        await expectLogic(logic, () => {
            logic.actions.ask()
        }).toDispatchActions(['setChatError'])
        expect(logic.values.asking).toBe(true)
        expect(logic.values.chatHasOpenTurn).toBe(true)
        expect(logic.values.chatError).toBe("Couldn't check the answer. Try again.")

        mockedGet.mockRejectedValue(new ApiError('missing', 404))
        await expectLogic(logic, () => {
            logic.actions.poll()
        }).toDispatchActions(['pollFailed'])
        expect(logic.values.asking).toBe(false)
    })

    it('clears the poll timer on unmount', async () => {
        const clear = jest.spyOn(window, 'clearInterval')
        mockedGet.mockReturnValue(new Promise(() => {}))
        logic.actions.setChatId('chat-1')
        logic.actions.setQuestion('Can I get a refund?')
        mockedAsk.mockResolvedValue(chat('running'))
        void logic.actions.ask()
        await expectLogic(logic).toDispatchActions(['startPolling'])
        logic.unmount()
        expect(clear).toHaveBeenCalled()
    })
})
