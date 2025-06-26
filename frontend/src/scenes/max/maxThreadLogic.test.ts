import { partial } from 'kea-test-utils'
import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'

import { maxContextLogic } from './maxContextLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import {
    maxMocks,
    MOCK_CONVERSATION_ID,
    MOCK_IN_PROGRESS_CONVERSATION,
    MOCK_TEMP_CONVERSATION_ID,
    mockStream,
} from './testUtils'

describe('maxThreadLogic', () => {
    let logic: ReturnType<typeof maxThreadLogic.build>

    beforeEach(() => {
        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/environments/:team_id/conversations/:conversation_id/': MOCK_IN_PROGRESS_CONVERSATION,
            },
        })
        initKeaTests()

        // Mock the dataProcessingAccepted selector to return true
        const maxGlobalLogicInstance = maxGlobalLogic()
        maxGlobalLogicInstance.mount()
        jest.spyOn(maxGlobalLogicInstance.selectors, 'dataProcessingAccepted').mockReturnValue(true)

        logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID })
        logic.mount()
    })

    afterEach(() => {
        // Stop any active polling/streaming in maxLogic
        const maxLogicInstance = maxLogic.findMounted()
        if (maxLogicInstance) {
            maxLogicInstance.cache.eventSourceController?.abort()
            maxLogicInstance.unmount()
        }

        // Stop any active streaming in the thread logic
        if (logic.cache?.generationController) {
            logic.cache.generationController.abort()
        }

        // Unmount the maxGlobalLogic
        const maxGlobalLogicInstance = maxGlobalLogic.findMounted()
        if (maxGlobalLogicInstance) {
            maxGlobalLogicInstance.unmount()
        }

        sidePanelStateLogic.unmount()
        logic?.unmount()

        // Clean up any remaining mocks
        jest.restoreAllMocks()
    })

    it('selects threadGroup without a human message', async () => {
        await expectLogic(logic, () => {
            logic.actions.setThread([
                {
                    type: AssistantMessageType.Assistant,
                    content: 'hello',
                    status: 'completed',
                    id: 'mock-assistant-msg-1',
                },
            ])
        }).toMatchValues({
            threadGrouped: [
                [
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'hello',
                        status: 'completed',
                        id: 'mock-assistant-msg-1',
                    },
                ],
            ],
        })
    })

    it('preserves only the latest reasoning message in threadGrouped', async () => {
        await expectLogic(logic, () => {
            logic.actions.setThread([
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-1',
                },
                {
                    type: AssistantMessageType.Reasoning,
                    content: 'hello',
                    status: 'completed',
                    id: 'reasoning-1',
                },
                {
                    type: AssistantMessageType.Reasoning,
                    content: 'hello',
                    status: 'completed',
                    id: 'reasoning-2',
                },
            ])
        }).toMatchValues({
            threadGrouped: [
                [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                ],
                [
                    {
                        type: AssistantMessageType.Reasoning,
                        content: 'hello',
                        status: 'completed',
                        id: 'reasoning-2',
                    },
                ],
            ],
        })
    })

    it('groups thread correctly', async () => {
        await expectLogic(logic, () => {
            logic.actions.setThread([
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-1',
                },
                {
                    type: AssistantMessageType.Reasoning,
                    content: 'hello',
                    status: 'completed',
                    id: 'reasoning-1',
                },
                {
                    type: AssistantMessageType.Reasoning,
                    content: 'hello',
                    status: 'completed',
                    id: 'reasoning-2',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'hello',
                    status: 'completed',
                    id: 'assistant-1',
                },
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-2',
                },
            ])
        }).toMatchValues({
            threadGrouped: [
                [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                ],
                [
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'hello',
                        status: 'completed',
                        id: 'assistant-1',
                    },
                ],
                [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-2',
                    },
                ],
            ],
        })
    })

    it('preserves the reasoning message when the assistant message is without id', async () => {
        await expectLogic(logic, () => {
            logic.actions.setThread([
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-1',
                },
                {
                    type: AssistantMessageType.Reasoning,
                    content: 'hello',
                    status: 'completed',
                    id: 'reasoning-1',
                },
                {
                    type: AssistantMessageType.Reasoning,
                    content: 'hello',
                    status: 'completed',
                    id: 'reasoning-2',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'hello',
                    status: 'completed',
                },
            ])
        }).toMatchValues({
            threadGrouped: [
                [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                ],
                [
                    {
                        type: AssistantMessageType.Reasoning,
                        content: 'hello',
                        status: 'completed',
                        id: 'reasoning-2',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'hello',
                        status: 'completed',
                    },
                ],
            ],
        })
    })

    it('adds a thinking message to an ephemeral group', async () => {
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID })
        logic.mount()

        // Only a human message–should create an ephemeral group
        await expectLogic(logic, () => {
            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            logic.actions.setThread([
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-1',
                },
            ])
        }).toMatchValues({
            threadGrouped: [
                [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                ],
                [
                    partial({
                        type: AssistantMessageType.Reasoning,
                        status: 'completed',
                        id: 'loader',
                    }),
                ],
            ],
        })
    })

    it('adds a thinking message to the last group of messages with IDs', async () => {
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID })
        logic.mount()

        // Human and assistant messages with IDs–should append to the last group
        await expectLogic(logic, () => {
            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            logic.actions.setThread([
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-1',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'hello',
                    status: 'completed',
                    id: 'assistant-1',
                },
            ])
        }).toMatchValues({
            threadGrouped: [
                [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                ],
                [
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'hello',
                        status: 'completed',
                        id: 'assistant-1',
                    },
                    partial({
                        type: AssistantMessageType.Reasoning,
                        status: 'completed',
                        id: 'loader',
                    }),
                ],
            ],
        })
    })

    it('does not add a thinking message when the last message is without ID', async () => {
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID })
        logic.mount()

        // Human with ID and assistant messages without ID–should not add the message
        await expectLogic(logic, () => {
            logic.actions.setThread([
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-1',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'hello',
                    status: 'completed',
                },
            ])
        }).toMatchValues({
            threadGrouped: [
                [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                ],
                [
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'hello',
                        status: 'completed',
                    },
                ],
            ],
        })
    })

    it('adds a thinking message when the thread is completely empty', async () => {
        const streamSpy = mockStream()
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.askMax('hello')
        }).toMatchValues({
            threadGrouped: [
                [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                    },
                ],
                [
                    partial({
                        type: AssistantMessageType.Reasoning,
                        status: 'completed',
                        id: 'loader',
                    }),
                ],
            ],
        })
        expect(streamSpy).toHaveBeenCalledTimes(1)
    })

    describe('compiledContext integration', () => {
        let maxContextLogicInstance: ReturnType<typeof maxContextLogic.build>

        beforeEach(() => {
            maxContextLogicInstance = maxContextLogic()
            maxContextLogicInstance.mount()
        })

        afterEach(() => {
            jest.restoreAllMocks()
            // Stop any active polling/streaming
            if (logic.cache?.generationController) {
                logic.cache.generationController.abort()
            }
            maxContextLogicInstance?.unmount()
        })

        it('sends compiledContext as ui_context when compiledContext is present', async () => {
            const streamSpy = mockStream()

            // Add context data to maxContextLogic so hasData becomes true
            maxContextLogicInstance.actions.addOrUpdateContextDashboard({
                id: 1,
                name: 'Test Dashboard',
                description: 'Test description',
                tiles: [],
            } as any)

            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.askMax('test prompt')
                // Immediately complete to avoid waiting for async operations
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['askMax', 'completeThreadGeneration'])

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: 'test prompt',
                    ui_context: expect.objectContaining({
                        dashboards: expect.any(Object),
                    }),
                }),
                expect.any(Object)
            )
        })

        it('sends undefined as ui_context when compiledContext is null', async () => {
            const streamSpy = mockStream()

            // Don't add any context data, so compiledContext will be null
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.askMax('test prompt')
                // Immediately complete to avoid waiting for async operations
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['askMax', 'completeThreadGeneration'])

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: 'test prompt',
                    ui_context: undefined,
                }),
                expect.any(Object)
            )
        })
    })
})
