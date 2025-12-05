import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'

import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import { MOCK_IN_PROGRESS_CONVERSATION, mockStream } from './testUtils'
import { MOCK_CONVERSATION_ID, maxMocks } from './testUtils'

describe('Max Logics Integration Tests', () => {
    let logic: ReturnType<typeof maxLogic.build>
    let threadLogic: ReturnType<typeof maxThreadLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()

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

        logic = maxLogic({ tabId: 'test' })
        logic.mount()
        threadLogic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, tabId: 'test' })
        threadLogic.mount()

        // Wait for all the microtasks to finish
        await expectLogic(threadLogic, () => {
            // start a thread
            threadLogic.actions.askMax('hello')
        })

        // update props
        maxThreadLogic({
            tabId: 'test',
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
})
