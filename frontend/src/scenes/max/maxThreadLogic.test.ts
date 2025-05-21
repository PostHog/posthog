import { partial } from 'kea-test-utils'
import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'

import {
    maxMocks,
    MOCK_CONVERSATION_ID,
    MOCK_IN_PROGRESS_CONVERSATION,
    MOCK_TEMP_CONVERSATION_ID,
    mockStream,
} from './__tests__/utils'
import { maxThreadLogic } from './maxThreadLogic'

describe('maxThreadLogic', () => {
    let logic: ReturnType<typeof maxThreadLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID })
        logic.mount()
    })

    afterEach(() => {
        sidePanelStateLogic.unmount()
        logic?.unmount()
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
})
