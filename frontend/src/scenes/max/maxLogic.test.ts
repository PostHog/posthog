import { ReadableStream } from 'node:stream/web'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import api from 'lib/api'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AssistantEventType, AssistantMessage, AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'
import { Conversation, ConversationStatus } from '~/types'

import { maxLogic } from './maxLogic'

describe('maxLogic', () => {
    let logic: ReturnType<typeof maxLogic.build>

    function mockStream(): jest.SpyInstance {
        return jest.spyOn(api.conversations, 'stream').mockImplementation(async (payload): Promise<Response> => {
            const encoder = new TextEncoder()
            const stream = new ReadableStream({
                async start(controller) {
                    function enqueue({ event, data }: { event: AssistantEventType; data: any }): void {
                        controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
                    }

                    const conversation: Conversation = {
                        id: 'mock-conversation-id-from-stream',
                        status: ConversationStatus.InProgress,
                        title: '',
                        created_at: new Date().toISOString(),
                        updated_at: new Date().toISOString(),
                    }
                    enqueue({
                        event: AssistantEventType.Conversation,
                        data: conversation,
                    })

                    // Clear queues
                    await new Promise((r) => setTimeout(r))

                    // Simulate the main assistant response
                    const assistantResponseMessage: AssistantMessage = {
                        id: 'mock-assistant-msg-1', // Finalized messages usually have an ID
                        type: AssistantMessageType.Assistant,
                        content: `Response to "${payload?.content}"`, // Use input from payload
                    }
                    enqueue({
                        event: AssistantEventType.Message,
                        data: assistantResponseMessage,
                    })

                    // Clear queues
                    await new Promise((r) => setTimeout(r))

                    // Close the stream
                    controller.close()
                },
            })

            const response = {
                body: {
                    getReader: () => stream.getReader(),
                },
            }

            return response as any
        })
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        sidePanelStateLogic.unmount()
        logic?.unmount()
    })

    it("doesn't mount sidePanelStateLogic if it's not already mounted", async () => {
        // Mount maxLogic after setting up the sidePanelStateLogic state
        logic = maxLogic()
        logic.mount()

        // Check that sidePanelStateLogic was not mounted
        expect(sidePanelStateLogic.isMounted()).toBe(false)
    })

    it('sets the question when URL has hash param #panel=max:Foo', async () => {
        // Set up router with #panel=max:Foo
        router.actions.push('', {}, { panel: 'max:Foo' })
        sidePanelStateLogic.mount()

        // Mount maxLogic after setting up the sidePanelStateLogic state
        logic = maxLogic()
        logic.mount()

        // Check that the question has been set to "Foo" (via sidePanelStateLogic automatically)
        await expectLogic(logic).toMatchValues({
            question: 'Foo',
        })
    })

    it('calls askMax when URL has hash param #panel=max:!Foo', async () => {
        // Set up router with #panel=max:!Foo
        router.actions.push('', {}, { panel: 'max:!Foo' })
        sidePanelStateLogic.mount()

        // Spy on askMax action
        // Must create the logic first to spy on its actions
        logic = maxLogic()
        const askMaxSpy = jest.spyOn(logic.actions, 'askMax')

        // Only mount maxLogic after setting up the router and sidePanelStateLogic
        logic.mount()

        // Check that askMax has been called with "Foo" (via sidePanelStateLogic automatically)
        expect(askMaxSpy).toHaveBeenCalledWith('Foo')
    })

    it('does not reset the thread when it was already opened after conversations have been loaded', async () => {
        // mock api
        jest.spyOn(api.conversations, 'list').mockImplementation(async () => {
            await new Promise((resolve) => setTimeout(resolve))
            return {
                results: [],
            }
        })

        const streamSpy = mockStream()

        // mount logic
        logic = maxLogic()

        // Wait for all the microtasks to finish
        await expectLogic(logic, () => {
            logic.mount()

            // start a thread
            logic.actions.askMax('hello')
        }).delay(10)

        expect(streamSpy).toHaveBeenCalledTimes(1)

        await expectLogic(logic).toMatchValues({
            threadGrouped: [
                [
                    {
                        content: 'hello',
                        status: 'completed',
                        type: 'human',
                    },
                ],
                [
                    {
                        content: 'Response to "hello"',
                        id: 'mock-assistant-msg-1',
                        status: 'completed',
                        type: 'ai',
                    },
                ],
            ],
        })
    })
})
