import { router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'

import { SIDE_PANEL_CONVERSATION_KEY } from './max-storage-keys'
import { maxGlobalLogic } from './maxGlobalLogic'
import { SIDE_PANEL_PANEL_ID, maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { MOCK_IN_PROGRESS_CONVERSATION, mockStream } from './testUtils'
import { MOCK_CONVERSATION_ID, maxMocks } from './testUtils'

describe('Max Logics Integration Tests', () => {
    let logic: ReturnType<typeof maxLogic.build>
    let threadLogic: ReturnType<typeof maxThreadLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        // The side panel instance persists/restores its conversation here; stale state would leak across tests.
        sessionStorage.removeItem(SIDE_PANEL_CONVERSATION_KEY)

        // Mock the dataProcessingAccepted selector to return true
        const maxGlobalLogicInstance = maxGlobalLogic()
        maxGlobalLogicInstance.mount()
        jest.spyOn(maxGlobalLogicInstance.selectors, 'dataProcessingAccepted').mockReturnValue(true)
    })

    afterEach(() => {
        logic?.unmount()
        threadLogic?.unmount()

        // Unmount the maxGlobalLogic
        const maxGlobalLogicInstance = maxGlobalLogic.findMounted()
        if (maxGlobalLogicInstance) {
            maxGlobalLogicInstance.unmount()
        }

        // Clean up any remaining mocks
        jest.restoreAllMocks()
    })

    it('does not update conversation and thread when stream is active', async () => {
        const streamSpy = mockStream()

        logic = maxLogic({ panelId: 'test' })
        logic.mount()
        // Set the conversation ID so activeThreadKey matches the thread logic's conversationId
        logic.actions.setConversationId(MOCK_CONVERSATION_ID)
        threadLogic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
        threadLogic.mount()

        // Wait for all the microtasks to finish
        await expectLogic(threadLogic, () => {
            // start a thread
            threadLogic.actions.askMax('hello')
        })

        // update props
        maxThreadLogic({
            panelId: 'test',
            conversationId: MOCK_CONVERSATION_ID,
            conversation: {
                ...MOCK_IN_PROGRESS_CONVERSATION,
                messages: [
                    {
                        content: 'hello2',
                        type: AssistantMessageType.Assistant,
                        id: 'test-id',
                    },
                ],
            },
        })

        expect(streamSpy).toHaveBeenCalledTimes(1)

        await expectLogic(threadLogic).toMatchValues({
            threadGrouped: [
                {
                    content: 'hello',
                    status: 'completed',
                    type: AssistantMessageType.Human,
                    trace_id: expect.any(String),
                },
                partial({
                    type: AssistantMessageType.Assistant,
                    status: 'completed',
                    id: 'loader',
                    meta: partial({
                        thinking: expect.any(Array),
                    }),
                }),
            ],
        })
    })

    it('side panel conversation survives navigating to /ai without ?chat', async () => {
        logic = maxLogic({ panelId: SIDE_PANEL_PANEL_ID })
        logic.mount()
        logic.actions.setConversationId(MOCK_CONVERSATION_ID)

        router.actions.push(urls.ai())

        await expectLogic(logic).toNotHaveDispatchedActions(['startNewConversation'])
        expect(logic.values.conversationId).toEqual(MOCK_CONVERSATION_ID)
        // The active conversation is persisted per tab so a full page load can restore it.
        expect(sessionStorage.getItem(SIDE_PANEL_CONVERSATION_KEY)).toEqual(MOCK_CONVERSATION_ID)
    })

    it('scene chat still resets when navigating to /ai without ?chat', async () => {
        logic = maxLogic({ panelId: 'scene-tab-1' })
        logic.mount()
        logic.actions.setConversationId(MOCK_CONVERSATION_ID)

        router.actions.push(urls.ai())

        await expectLogic(logic).toDispatchActions(['startNewConversation'])
        expect(logic.values.conversationId).toBeNull()
    })

    it('side panel restores the persisted conversation on mount', async () => {
        sessionStorage.setItem(SIDE_PANEL_CONVERSATION_KEY, MOCK_CONVERSATION_ID)

        logic = maxLogic({ panelId: SIDE_PANEL_PANEL_ID })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['openConversation'])
        expect(logic.values.conversationId).toEqual(MOCK_CONVERSATION_ID)
    })
})
