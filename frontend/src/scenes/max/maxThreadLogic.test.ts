import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { partial } from 'kea-test-utils'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'
import React from 'react'

import api, { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookTarget } from 'scenes/notebooks/types'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import * as notebooksModel from '~/models/notebooksModel'
import {
    AgentMode,
    AssistantEventType,
    AssistantMessage,
    AssistantMessageType,
    HumanMessage,
    SlashCommandName,
} from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'
import { Conversation, ConversationDetail, ConversationStatus, ConversationType } from '~/types'

import { runStreamLogic } from 'products/posthog_ai/frontend/api/logics'

import { EnhancedToolCall, TOOL_DEFINITIONS } from './max-constants'
import { maxContextLogic } from './maxContextLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { MAX_DASHBOARD_CONTEXT_WAIT_MS, maxThreadLogic } from './maxThreadLogic'
import { MaxContextType } from './maxTypes'
import {
    MOCK_CONVERSATION,
    MOCK_CONVERSATION_ID,
    MOCK_IN_PROGRESS_CONVERSATION,
    MOCK_TEMP_CONVERSATION_ID,
    maxMocks,
    mockStream,
} from './testUtils'

jest.mock(
    '@posthog/hogvm',
    () => ({
        exec: jest.fn(),
        execAsync: jest.fn(),
    }),
    { virtual: true }
)

describe('maxThreadLogic', () => {
    let logic: ReturnType<typeof maxThreadLogic.build>
    let maxLogicInstance: ReturnType<typeof maxLogic.build>

    beforeEach(() => {
        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/environments/:team_id/conversations/:conversation_id/': MOCK_IN_PROGRESS_CONVERSATION,
                // loadQueueData fires on mount; without a shaped default it hits the empty-response
                // floor (no `messages`/`max_queue_messages`) and the queue reducers reduce to undefined.
                '/api/environments/:team_id/conversations/:conversation_id/queue': {
                    messages: [],
                    max_queue_messages: 0,
                },
            },
        })
        initKeaTests()

        // Mock the dataProcessingAccepted selector to return true
        const maxGlobalLogicInstance = maxGlobalLogic()
        maxGlobalLogicInstance.mount()
        jest.spyOn(maxGlobalLogicInstance.selectors, 'dataProcessingAccepted').mockReturnValue(true)

        // Set up maxLogic with matching conversationId so that activeThreadKey matches
        maxLogicInstance = maxLogic({ panelId: 'test' })
        maxLogicInstance.mount()
        maxLogicInstance.actions.setConversationId(MOCK_CONVERSATION_ID)

        logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
        logic.mount()
    })

    afterEach(() => {
        // Stop any active streaming in the thread logic
        if (logic.cache?.generationController) {
            logic.cache.generationController.abort()
        }

        sidePanelStateLogic.unmount()
        logic?.unmount()

        // Stop any active polling/streaming in maxLogic
        if (maxLogicInstance) {
            maxLogicInstance.cache.eventSourceController?.abort()
            maxLogicInstance.unmount()
        }

        // Clean up any remaining mocks
        jest.restoreAllMocks()
    })

    it('builds for the bare scene without a panelId, falling back to the scene key', () => {
        const sceneLogic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID })
        expect(() => sceneLogic.mount()).not.toThrow()
        expect(sceneLogic.key).toBe(`${MOCK_CONVERSATION_ID}-scene`)
        sceneLogic.unmount()
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
                {
                    type: AssistantMessageType.Assistant,
                    content: 'hello',
                    status: 'completed',
                    id: 'mock-assistant-msg-1',
                },
            ],
        })
    })

    it('groups assistant messages with thinking correctly', async () => {
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
                    content: 'response',
                    status: 'completed',
                    id: 'assistant-1',
                    meta: {
                        thinking: [{ thinking: 'Processing request' }],
                    },
                },
            ])
        }).toMatchValues({
            threadGrouped: [
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-1',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'response',
                    status: 'completed',
                    id: 'assistant-1',
                    meta: {
                        thinking: [{ thinking: 'Processing request' }],
                    },
                },
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
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-2',
                },
            ],
        })
    })

    it('groups assistant messages without id correctly', async () => {
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
            ],
        })
    })

    it('adds a thinking message to an ephemeral group', async () => {
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
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
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    id: 'human-1',
                },
                partial({
                    type: AssistantMessageType.Assistant,
                    meta: partial({ thinking: expect.any(Array) }),
                    status: 'completed',
                    id: 'loader',
                }),
            ],
        })
    })

    it('adds a thinking message to the last group of messages with IDs', async () => {
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
        logic.mount()

        // Human and assistant messages with IDs–should append thinking message
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
                partial({
                    type: AssistantMessageType.Assistant,
                    meta: partial({ thinking: expect.any(Array) }),
                    status: 'completed',
                    id: 'loader',
                }),
            ],
        })
    })

    it('does not add a thinking message when the last message is without ID', async () => {
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
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
            ],
        })
    })

    it('adds a thinking message when the thread is completely empty', async () => {
        const streamSpy = mockStream()
        logic.unmount()
        maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
        logic.mount()

        expect(streamSpy).toHaveBeenCalledTimes(0)
        await expectLogic(logic, () => {
            logic.actions.askMax('hello')
        }).toMatchValues({
            threadGrouped: [
                {
                    type: AssistantMessageType.Human,
                    content: 'hello',
                    status: 'completed',
                    trace_id: expect.any(String),
                },
                partial({
                    type: AssistantMessageType.Assistant,
                    meta: partial({ thinking: expect.any(Array) }),
                    status: 'completed',
                    id: 'loader',
                }),
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

            maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
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
            maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
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

        // Simulate being on a dashboard scene whose data has not loaded yet: dashboardLogic.dashboard
        // is null, so its maxContext returns []. The first message must wait for the load, otherwise
        // it ships with no dashboard context and Max can't see the open dashboard.
        const mockLoadingDashboardScene = (): { values: { dashboard: any } } => {
            const fakeDashboardLogic: any = {
                selectors: {
                    maxContext: () =>
                        fakeDashboardLogic.values.dashboard
                            ? [{ type: MaxContextType.DASHBOARD, data: fakeDashboardLogic.values.dashboard }]
                            : [],
                },
                values: { dashboard: null as any },
            }
            jest.spyOn(sceneLogic.selectors, 'activeSceneId').mockReturnValue(Scene.Dashboard)
            jest.spyOn(sceneLogic.selectors, 'activeSceneLogic').mockReturnValue(fakeDashboardLogic)
            jest.spyOn(sceneLogic.selectors, 'activeLoadedScene').mockReturnValue({
                paramsToProps: () => ({ id: 1 }),
                sceneParams: {},
            } as any)
            return fakeDashboardLogic
        }

        it('waits for the open dashboard to load before sending the first message (regression for #61414)', async () => {
            jest.useFakeTimers()
            const captureSpy = jest.spyOn(posthog, 'capture')
            try {
                const streamSpy = mockStream()
                const fakeDashboardLogic = mockLoadingDashboardScene()

                maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
                logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
                logic.mount()

                // Fire the first message while the dashboard is still loading.
                logic.actions.askMax('what am I seeing on this dashboard?')

                // The gate holds the send while the dashboard is loading.
                await jest.advanceTimersByTimeAsync(300)
                expect(streamSpy).toHaveBeenCalledTimes(0)

                // Dashboard finishes loading -> gate releases -> the message sends WITH the dashboard context.
                fakeDashboardLogic.values.dashboard = { id: 1, name: 'Test Dashboard', tiles: [] }
                await jest.advanceTimersByTimeAsync(500)

                expect(streamSpy).toHaveBeenCalledTimes(1)
                expect(streamSpy).toHaveBeenCalledWith(
                    expect.objectContaining({
                        ui_context: expect.objectContaining({
                            dashboards: expect.arrayContaining([expect.objectContaining({ id: 1 })]),
                        }),
                    }),
                    expect.any(Object)
                )
                // A normal load must NOT report a timeout.
                expect(captureSpy).not.toHaveBeenCalledWith('max dashboard context wait timed out', expect.anything())
            } finally {
                jest.useRealTimers()
            }
        })

        it('reports a telemetry event and still sends if the dashboard never loads within the cap', async () => {
            jest.useFakeTimers()
            const captureSpy = jest.spyOn(posthog, 'capture')
            try {
                const streamSpy = mockStream()
                mockLoadingDashboardScene() // dashboard stays null past the wait cap

                maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
                logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
                logic.mount()

                logic.actions.askMax('what am I seeing on this dashboard?')

                // Advance past the 8s wait cap without the dashboard ever loading.
                await jest.advanceTimersByTimeAsync(8100)

                // The cap must never block the user - the message still sends...
                expect(streamSpy).toHaveBeenCalledTimes(1)
                // ...but we record that the wait timed out, so the cap's impact is observable in prod.
                expect(captureSpy).toHaveBeenCalledWith(
                    'max dashboard context wait timed out',
                    expect.objectContaining({ dashboard_id: 1, waited_ms: expect.any(Number) })
                )
                // waited_ms is real elapsed time, so it must be at least the cap (never under-reported).
                const timeoutCall = captureSpy.mock.calls.find((c) => c[0] === 'max dashboard context wait timed out')
                expect(timeoutCall?.[1]?.waited_ms).toBeGreaterThanOrEqual(MAX_DASHBOARD_CONTEXT_WAIT_MS)
            } finally {
                jest.useRealTimers()
            }
        })

        it('releases the gate and sends if the user navigates away while the dashboard is still loading', async () => {
            jest.useFakeTimers()
            try {
                const streamSpy = mockStream()
                mockLoadingDashboardScene()

                maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
                logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
                logic.mount()

                logic.actions.askMax('what am I seeing on this dashboard?')

                // Still on the (never-loading) dashboard -> the gate holds.
                await jest.advanceTimersByTimeAsync(300)
                expect(streamSpy).toHaveBeenCalledTimes(0)

                // User leaves the dashboard before it ever loads. The gate re-reads the scene each tick,
                // so it must stop waiting and send rather than block until the timeout.
                jest.spyOn(sceneLogic.selectors, 'activeSceneId').mockReturnValue(Scene.SavedInsights)
                jest.spyOn(sceneLogic.selectors, 'activeSceneLogic').mockReturnValue(null as any)
                await jest.advanceTimersByTimeAsync(300)

                expect(streamSpy).toHaveBeenCalledTimes(1)
            } finally {
                jest.useRealTimers()
            }
        })

        it('sends form_answers in ui_context when provided', async () => {
            const streamSpy = mockStream()

            maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
            logic.mount()

            const formAnswers = { q1: 'answer1', q2: 'answer2' }
            await expectLogic(logic, () => {
                logic.actions.askMax('Form response', false, { form_answers: formAnswers })
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['askMax', 'completeThreadGeneration'])

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: 'Form response',
                    ui_context: expect.objectContaining({
                        form_answers: formAnswers,
                    }),
                }),
                expect.any(Object)
            )
        })

        it('merges form_answers with existing compiled context', async () => {
            const streamSpy = mockStream()

            // Add context data to maxContextLogic
            maxContextLogicInstance.actions.addOrUpdateContextDashboard({
                id: 1,
                name: 'Test Dashboard',
                description: 'Test description',
                tiles: [],
            } as any)

            maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
            logic.mount()

            const formAnswers = { q1: 'answer1' }
            await expectLogic(logic, () => {
                logic.actions.askMax('Form with context', false, { form_answers: formAnswers })
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['askMax', 'completeThreadGeneration'])

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: 'Form with context',
                    ui_context: expect.objectContaining({
                        dashboards: expect.any(Object),
                        form_answers: formAnswers,
                    }),
                }),
                expect.any(Object)
            )
        })

        it('handles empty form_answers object', async () => {
            const streamSpy = mockStream()

            maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.askMax('Empty form', false, { form_answers: {} })
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['askMax', 'completeThreadGeneration'])

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: 'Empty form',
                    ui_context: expect.objectContaining({
                        form_answers: {},
                    }),
                }),
                expect.any(Object)
            )
        })
    })

    describe('queueing', () => {
        beforeEach(() => {
            featureFlagLogic.mount()
            jest.spyOn(api.conversations.queue, 'list').mockResolvedValue({
                messages: [],
                max_queue_messages: 2,
            })
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.POSTHOG_AI_QUEUE_MESSAGES_SYSTEM]: true,
            })
        })

        afterEach(() => {
            featureFlagLogic.unmount()
        })

        it('queues prompts while loading and omits null fields', async () => {
            const enqueueSpy = jest.spyOn(api.conversations.queue, 'enqueue').mockResolvedValue({
                messages: [],
                max_queue_messages: 2,
            })
            const streamSpy = mockStream()

            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            await new Promise((resolve) => setTimeout(resolve, 0))

            logic.actions.askMax('Queued prompt')
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(streamSpy).not.toHaveBeenCalled()
            expect(enqueueSpy).toHaveBeenCalledWith(
                MOCK_CONVERSATION_ID,
                expect.objectContaining({
                    content: 'Queued prompt',
                })
            )

            const queuedPayload = enqueueSpy.mock.calls[0][1]
            expect(queuedPayload).not.toHaveProperty('agent_mode')
            expect(queuedPayload).not.toHaveProperty('billing_context')
            expect(queuedPayload).not.toHaveProperty('ui_context')
        })

        it('includes ui_context and agent_mode when set', async () => {
            const enqueueSpy = jest.spyOn(api.conversations.queue, 'enqueue').mockResolvedValue({
                messages: [],
                max_queue_messages: 2,
            })
            mockStream()

            logic.actions.setAgentMode(AgentMode.SQL)
            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            await new Promise((resolve) => setTimeout(resolve, 0))

            logic.actions.askMax('Queued prompt', true, { form_answers: { q1: 'answer1' } })
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(enqueueSpy).toHaveBeenCalledWith(
                MOCK_CONVERSATION_ID,
                expect.objectContaining({
                    content: 'Queued prompt',
                    agent_mode: AgentMode.SQL,
                    ui_context: { form_answers: { q1: 'answer1' } },
                })
            )
        })

        it('shows an error toast when the queue is full', async () => {
            const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(jest.fn())
            const enqueueSpy = jest.spyOn(api.conversations.queue, 'enqueue')

            logic.actions.setQueuedMessages([
                { id: 'queue-1', content: 'first', created_at: new Date().toISOString() },
                { id: 'queue-2', content: 'second', created_at: new Date().toISOString() },
            ])
            logic.actions.setQueueLimit(2)
            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            await new Promise((resolve) => setTimeout(resolve, 0))

            logic.actions.askMax('Queued prompt')
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(enqueueSpy).not.toHaveBeenCalled()
            expect(toastSpy).toHaveBeenCalledWith('You can only queue two messages at a time.')
        })

        it('updates queued messages from the API', async () => {
            const queueMessage = {
                id: 'queue-1',
                content: 'Original',
                created_at: new Date().toISOString(),
            }
            jest.spyOn(api.conversations.queue, 'update').mockResolvedValue({
                messages: [{ ...queueMessage, content: 'Updated' }],
                max_queue_messages: 2,
            })

            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            logic.actions.setQueuedMessages([queueMessage])
            logic.actions.setQueueLimit(2)

            logic.actions.updateQueuedMessage('queue-1', 'Updated')
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.queuedMessages).toEqual([{ ...queueMessage, content: 'Updated' }])
        })

        it('deletes queued messages from the API', async () => {
            const queueMessage = {
                id: 'queue-1',
                content: 'Original',
                created_at: new Date().toISOString(),
            }
            jest.spyOn(api.conversations.queue, 'delete').mockResolvedValue({
                messages: [],
                max_queue_messages: 2,
            })

            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            logic.actions.setQueuedMessages([queueMessage])
            logic.actions.setQueueLimit(2)

            logic.actions.deleteQueuedMessage(queueMessage.id)
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.queuedMessages).toEqual([])
        })

        it('clears queued messages when approvals are pending', async () => {
            jest.spyOn(api.conversations.queue, 'clear').mockResolvedValue({
                messages: [],
                max_queue_messages: 2,
            })

            logic.actions.setQueuedMessages([{ id: 'queue-1', content: 'First', created_at: new Date().toISOString() }])
            logic.actions.setQueueLimit(2)

            await expectLogic(logic, () => {
                logic.actions.setConversation({
                    ...MOCK_IN_PROGRESS_CONVERSATION,
                    pending_approvals: [
                        {
                            proposal_id: 'proposal-1',
                            decision_status: 'pending',
                            tool_name: 'create_form',
                            preview: 'Preview',
                            payload: {},
                        },
                    ],
                })
            }).toMatchValues({
                queuedMessages: [],
            })
        })

        it('loads queued messages on mount', async () => {
            const queueMessage = {
                id: 'queue-1',
                content: 'Queued',
                created_at: new Date().toISOString(),
            }
            ;(api.conversations.queue.list as jest.Mock).mockResolvedValue({
                messages: [queueMessage],
                max_queue_messages: 2,
            })

            logic.unmount()
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
            logic.mount()
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.queuedMessages).toEqual([])
        })

        it('consumes queued messages via the API', async () => {
            const queueMessage = {
                id: 'queue-1',
                content: 'Queued',
                created_at: new Date().toISOString(),
            }
            jest.spyOn(api.conversations.queue, 'delete').mockResolvedValue({
                messages: [],
                max_queue_messages: 2,
            })

            logic.actions.setQueuedMessages([queueMessage])
            logic.actions.setQueueLimit(2)

            await expectLogic(logic, () => {
                logic.actions.consumeQueuedMessage(queueMessage)
            }).toMatchValues({
                queuedMessages: [],
            })
        })

        it('clears queue state when switching conversations', async () => {
            const queueMessage = {
                id: 'queue-1',
                content: 'Queued',
                created_at: new Date().toISOString(),
            }
            const listSpy = jest.spyOn(api.conversations.queue, 'list').mockResolvedValue({
                messages: [],
                max_queue_messages: 2,
            })

            logic.actions.setQueuedMessages([queueMessage])
            logic.actions.setQueueLimit(2)

            logic.actions.setConversation({
                ...MOCK_IN_PROGRESS_CONVERSATION,
                id: 'new-conversation-id',
            })
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logic.values.queuedMessages).toEqual([])
            expect(listSpy).toHaveBeenCalledWith('new-conversation-id')
        })
    })

    describe('form resume actions', () => {
        it('resumes the conversation with submitted form answers', async () => {
            const streamSpy = mockStream()

            await expectLogic(logic, () => {
                logic.actions.continueAfterForm({ q1: 'answer1' })
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['continueAfterForm', 'streamConversation', 'completeThreadGeneration'])

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: null,
                    conversation: MOCK_CONVERSATION_ID,
                    resume_payload: { action: 'form', form_answers: { q1: 'answer1' } },
                }),
                expect.any(Object)
            )
        })

        it('resumes the conversation when the form is dismissed', async () => {
            const streamSpy = mockStream()

            await expectLogic(logic, () => {
                logic.actions.continueAfterFormDismissal()
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['continueAfterFormDismissal', 'streamConversation', 'completeThreadGeneration'])

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: null,
                    conversation: MOCK_CONVERSATION_ID,
                    resume_payload: { action: 'dismiss_form' },
                }),
                expect.any(Object)
            )
        })
    })

    describe('client tool execution round trip', () => {
        const pendingClientToolThread = (): any[] => [
            {
                type: AssistantMessageType.Human,
                content: 'Do the thing',
                id: 'human-1',
                status: 'completed',
            },
            {
                type: AssistantMessageType.Assistant,
                content: '',
                id: 'assistant-1',
                status: 'completed',
                tool_calls: [{ id: 'tc-1', name: 'search', args: { payload: 'data' } }],
            },
        ]

        it('runs the registered handler and resumes with its result, even while conversationLoading is still true', async () => {
            const streamSpy = mockStream()
            const clientExecution = jest.fn().mockResolvedValue({ ok: true })
            maxGlobalLogic().actions.registerTool({
                identifier: 'search',
                name: 'Search PostHog data',
                clientExecution,
            } as any)
            // The round trip must fire even though conversationLoading is still true at this point
            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            logic.actions.setThread(pendingClientToolThread())

            await expectLogic(logic, () => {
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['executePendingClientToolCall', 'continueWithClientToolResult', 'streamConversation'])

            expect(clientExecution).toHaveBeenCalledWith({ payload: 'data' })
            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: null,
                    conversation: MOCK_CONVERSATION_ID,
                    resume_payload: {
                        action: 'client_tool_result',
                        tool_call_id: 'tc-1',
                        result: { ok: true },
                    },
                }),
                expect.any(Object)
            )
        })

        it('resumes with a refusal when a statically-marked client tool has no registered handler', async () => {
            const streamSpy = mockStream()
            logic.actions.setThread(pendingClientToolThread())

            TOOL_DEFINITIONS['search'].clientExecuted = true
            try {
                await expectLogic(logic, () => {
                    logic.actions.completeThreadGeneration()
                }).toDispatchActions(['continueWithClientToolResult'])
            } finally {
                delete TOOL_DEFINITIONS['search'].clientExecuted
            }

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    resume_payload: expect.objectContaining({
                        action: 'client_tool_result',
                        tool_call_id: 'tc-1',
                        result: { client_execution_error: expect.stringContaining('no longer open') },
                    }),
                }),
                expect.any(Object)
            )
        })

        it('attempts the resume only once per tool call', async () => {
            mockStream()
            const clientExecution = jest.fn().mockResolvedValue({ ok: true })
            maxGlobalLogic().actions.registerTool({
                identifier: 'search',
                name: 'Search PostHog data',
                clientExecution,
            } as any)
            logic.actions.setThread(pendingClientToolThread())

            await expectLogic(logic, () => {
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['continueWithClientToolResult'])
            // A failing resume turn re-fires completeThreadGeneration with the same dangling call
            await expectLogic(logic, () => {
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['executePendingClientToolCall'])
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(clientExecution).toHaveBeenCalledTimes(1)
        })

        it('drops the resume when a newer turn replaced the pending call while the handler ran', async () => {
            const streamSpy = mockStream()
            let resolveHandler: (value: Record<string, unknown>) => void = () => {}
            const clientExecution = jest
                .fn()
                .mockImplementation(() => new Promise<Record<string, unknown>>((resolve) => (resolveHandler = resolve)))
            maxGlobalLogic().actions.registerTool({
                identifier: 'search',
                name: 'Search PostHog data',
                clientExecution,
            } as any)
            logic.actions.setThread(pendingClientToolThread())

            await expectLogic(logic, () => {
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['executePendingClientToolCall'])
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(clientExecution).toHaveBeenCalled()

            // A user message completes a whole new turn while the handler runs — resume must be dropped
            logic.actions.setThread([
                ...pendingClientToolThread(),
                { type: AssistantMessageType.Human, content: 'Never mind', id: 'human-2', status: 'completed' },
                { type: AssistantMessageType.Assistant, content: 'OK!', id: 'assistant-2', status: 'completed' },
            ] as any)
            resolveHandler({ ok: true })
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(streamSpy).not.toHaveBeenCalled()
        })

        it('does nothing when the turn has no pending client tool call', async () => {
            const streamSpy = mockStream()
            const clientExecution = jest.fn()
            maxGlobalLogic().actions.registerTool({
                identifier: 'search',
                name: 'Search PostHog data',
                clientExecution,
            } as any)
            logic.actions.setThread([
                {
                    type: AssistantMessageType.Assistant,
                    content: 'All done!',
                    id: 'assistant-1',
                    status: 'completed',
                } as any,
            ])

            await expectLogic(logic, () => {
                logic.actions.completeThreadGeneration()
            }).toDispatchActions(['executePendingClientToolCall'])
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(clientExecution).not.toHaveBeenCalled()
            expect(streamSpy).not.toHaveBeenCalled()
        })
    })

    describe('traceId functionality', () => {
        it('sets and stores traceId correctly', async () => {
            const testTraceId = 'test-trace-id-123'

            await expectLogic(logic, () => {
                logic.actions.setTraceId(testTraceId)
            }).toMatchValues({
                traceId: testTraceId,
            })
        })

        it('includes traceId in stream API calls', async () => {
            const streamSpy = mockStream()

            await expectLogic(logic, () => {
                logic.actions.askMax('test prompt')
            })

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: 'test prompt',
                    trace_id: expect.any(String),
                }),
                expect.any(Object)
            )
        })
    })

    describe('reconnectToStream', () => {
        it('calls streamConversation with conversation ID and null content', async () => {
            const streamSpy = mockStream()

            await expectLogic(logic, () => {
                logic.actions.reconnectToStream()
            })

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    conversation: MOCK_CONVERSATION_ID,
                    content: null,
                }),
                expect.any(Object)
            )
        })
    })

    describe('parallel conversation isolation', () => {
        it('only processes askMax for the active thread, not other mounted threads', async () => {
            const streamSpy = mockStream()

            // Create a second thread logic with a different conversation ID
            const otherConversationId = 'other-conversation-id'
            const otherLogic = maxThreadLogic({ conversationId: otherConversationId, panelId: 'test' })
            otherLogic.mount()

            // maxLogicInstance is still set to MOCK_CONVERSATION_ID (the first logic's conversation)
            // So the first logic should process askMax, but the second should not

            // Call askMax - this should only be processed by the first logic (matching activeThreadKey)
            await expectLogic(logic, () => {
                logic.actions.askMax('test message')
            })

            // The stream should be called with the first conversation's ID
            expect(streamSpy).toHaveBeenCalledTimes(1)
            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    conversation: MOCK_CONVERSATION_ID,
                    content: 'test message',
                }),
                expect.any(Object)
            )

            // The other logic should NOT have added the message to its thread
            expect(otherLogic.values.threadRaw).toHaveLength(0)

            // The first logic SHOULD have added the message to its thread
            expect(logic.values.threadRaw).toHaveLength(1)
            expect((logic.values.threadRaw[0] as HumanMessage).content).toBe('test message')

            otherLogic.unmount()
        })

        it('switches which thread processes askMax when activeThreadKey changes', async () => {
            const streamSpy = mockStream()

            // Create a second thread logic with a different conversation ID
            const otherConversationId = 'other-conversation-id'
            const otherLogic = maxThreadLogic({ conversationId: otherConversationId, panelId: 'test' })
            otherLogic.mount()

            // Now switch maxLogicInstance to point to the other conversation
            maxLogicInstance.actions.setConversationId(otherConversationId)

            // Call askMax on the other logic - now IT should process
            await expectLogic(otherLogic, () => {
                otherLogic.actions.askMax('message for other conversation')
            })

            // The stream should be called with the other conversation's ID
            expect(streamSpy).toHaveBeenCalledTimes(1)
            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    conversation: otherConversationId,
                    content: 'message for other conversation',
                }),
                expect.any(Object)
            )

            // The other logic SHOULD have added the message
            expect(otherLogic.values.threadRaw).toHaveLength(1)

            // The first logic should NOT have added any message
            expect(logic.values.threadRaw).toHaveLength(0)

            otherLogic.unmount()
        })
    })

    describe('failure message handling', () => {
        it('adds failure message and stops streaming when failure event received', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Human,
                        content: 'test question',
                        status: 'completed',
                        id: 'human-1',
                    },
                ])
                // Simulate receiving a failure message
                logic.actions.addMessage({
                    type: AssistantMessageType.Failure,
                    content: 'Something went wrong',
                    status: 'completed',
                    id: 'failure-1',
                })
            }).toMatchValues({
                threadGrouped: [
                    {
                        type: AssistantMessageType.Human,
                        content: 'test question',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Failure,
                        content: 'Something went wrong',
                        status: 'completed',
                        id: 'failure-1',
                    },
                ],
            })
        })
    })

    describe('generation error status handling', () => {
        it('sets message status to error and stops streaming on generation error', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Human,
                        content: 'test question',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'partial response',
                        status: 'loading',
                        id: 'assistant-1',
                    },
                ])
                // Simulate setting error status
                logic.actions.setMessageStatus(1, 'error')
            }).toMatchValues({
                threadRaw: [
                    {
                        type: AssistantMessageType.Human,
                        content: 'test question',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'partial response',
                        status: 'error',
                        id: 'assistant-1',
                    },
                ],
            })
        })
    })

    describe('400 error message handling', () => {
        it('surfaces server detail message for 400 errors', async () => {
            jest.spyOn(api.conversations, 'stream').mockRejectedValue(
                new ApiError('Bad Request', 400, undefined, { detail: 'The server error message' })
            )

            logic.unmount()
            maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.askMax('hello')
            })
                .toDispatchActions(['askMax', 'addMessage', 'completeThreadGeneration'])
                .toMatchValues({
                    threadGrouped: expect.arrayContaining([
                        expect.objectContaining({
                            type: AssistantMessageType.Failure,
                            content: 'The server error message',
                        }),
                    ]),
                })
        })

        it('shows content length message for 400 errors with content attr', async () => {
            jest.spyOn(api.conversations, 'stream').mockRejectedValue(
                new ApiError('Bad Request', 400, undefined, { attr: 'content', detail: 'Content too long' })
            )

            logic.unmount()
            maxLogicInstance.actions.setConversationId(MOCK_TEMP_CONVERSATION_ID)
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.askMax('hello')
            })
                .toDispatchActions(['askMax', 'addMessage', 'completeThreadGeneration'])
                .toMatchValues({
                    threadGrouped: expect.arrayContaining([
                        expect.objectContaining({
                            type: AssistantMessageType.Failure,
                            content: 'Oops! Your message is too long. Ensure it has no more than 40000 characters.',
                        }),
                    ]),
                })
        })
    })

    describe('processNotebookUpdate', () => {
        it('navigates to notebook when not already on notebook page', async () => {
            router.actions.push(urls.ai())

            // Mock openNotebook to track its calls
            const openNotebookSpy = jest.spyOn(notebooksModel, 'openNotebook')
            openNotebookSpy.mockImplementation(async (notebookId, _target, _, callback) => {
                const logic = notebookLogic({ shortId: notebookId })
                logic.mount()
                if (callback) {
                    callback(logic)
                }
                router.actions.push(urls.notebook(notebookId))
            })

            await expectLogic(logic, () => {
                logic.actions.processNotebookUpdate('test-notebook-id', { type: 'doc', content: [] } as any)
            }).toDispatchActions(['processNotebookUpdate'])

            expect(openNotebookSpy).toHaveBeenCalledWith(
                'test-notebook-id',
                NotebookTarget.Scene,
                undefined,
                expect.any(Function)
            )
            expect(router.values.location.pathname).toContain(urls.notebook('test-notebook-id'))
        })

        it('updates existing notebook when already on notebook page', async () => {
            const notebookId = 'test-notebook-id'
            router.actions.push(urls.notebook(notebookId))

            const notebookLogicInstance = notebookLogic({ shortId: notebookId })
            notebookLogicInstance.mount()

            // Create spies BEFORE calling the action
            const setLocalContentSpy = jest.spyOn(notebookLogicInstance.actions, 'setLocalContent')
            const findMountedSpy = jest.spyOn(notebookLogic, 'findMounted')
            findMountedSpy.mockReturnValue(notebookLogicInstance)
            const routerActionsSpy = jest.spyOn(router.actions, 'push')

            await expectLogic(logic, () => {
                logic.actions.processNotebookUpdate(notebookId, { type: 'doc', content: [] } as any)
            }).toDispatchActions(['processNotebookUpdate'])

            expect(findMountedSpy).toHaveBeenCalledWith({ shortId: notebookId })
            expect(routerActionsSpy).not.toHaveBeenCalled()
            expect(setLocalContentSpy).toHaveBeenCalledWith({ type: 'doc', content: [] }, true, true)
        })

        it('handles gracefully when notebook logic is not mounted on notebook page', async () => {
            const notebookId = 'test-notebook-id'
            router.actions.push(urls.notebook(notebookId))

            // Create spies BEFORE calling the action
            const routerActionsSpy = jest.spyOn(router.actions, 'push')
            const notebookLogicFindMountedSpy = jest.spyOn(notebookLogic, 'findMounted')
            notebookLogicFindMountedSpy.mockReturnValue(null)

            await expectLogic(logic, () => {
                logic.actions.processNotebookUpdate(notebookId, { type: 'doc', content: [] } as any)
            }).toDispatchActions(['processNotebookUpdate'])

            expect(notebookLogicFindMountedSpy).toHaveBeenCalledWith({ shortId: notebookId })
            expect(routerActionsSpy).not.toHaveBeenCalled()
        })
    })

    describe('threadRaw status fields', () => {
        it('initializes threadRaw with status fields from conversation messages', async () => {
            const conversationWithMessages: ConversationDetail = {
                id: MOCK_CONVERSATION_ID,
                status: ConversationStatus.Idle,
                title: 'Test conversation',
                user: MOCK_DEFAULT_BASIC_USER,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                messages: [
                    {
                        type: AssistantMessageType.Human,
                        content: 'Initial question',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Initial response',
                        id: 'assistant-1',
                    },
                ],
                type: ConversationType.Assistant,
            }

            // Create logic with conversation containing messages
            logic.unmount()
            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: conversationWithMessages,
            })
            logic.mount()

            // Check that threadRaw has messages with status fields
            expect(logic.values.threadRaw).toEqual([
                {
                    type: AssistantMessageType.Human,
                    content: 'Initial question',
                    id: 'human-1',
                    status: 'completed',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'Initial response',
                    id: 'assistant-1',
                    status: 'completed',
                },
            ])
        })

        it('initializes threadRaw as empty array when conversation has no messages', async () => {
            const conversationWithoutMessages: ConversationDetail = {
                id: MOCK_CONVERSATION_ID,
                status: ConversationStatus.Idle,
                title: 'Empty conversation',
                user: MOCK_DEFAULT_BASIC_USER,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                messages: [],
                type: ConversationType.Assistant,
            }

            // Create logic with conversation containing no messages
            logic.unmount()
            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: conversationWithoutMessages,
            })
            logic.mount()

            // Check that threadRaw is empty
            expect(logic.values.threadRaw).toEqual([])
        })

        it('loads full conversation details when mounted from a history entry without messages', async () => {
            const conversationWithoutMessages: ConversationDetail = {
                id: MOCK_CONVERSATION_ID,
                status: ConversationStatus.Idle,
                title: 'History entry',
                user: MOCK_DEFAULT_BASIC_USER,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                type: ConversationType.Assistant,
            }

            logic.unmount()
            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: conversationWithoutMessages,
            })

            await expectLogic(logic, () => {
                logic.mount()
            }).toDispatchActions(['loadConversation'])
        })

        it('populates the thread before reconnecting when mounted on an in-progress stream', async () => {
            // afterMount must load the conversation and hydrate threadRaw BEFORE calling
            // reconnectToStream — otherwise the propsChanged-driven setThread would fire
            // after the reconnected stream has already pushed tokens, clobbering them.
            const loadedMessages = [
                { type: AssistantMessageType.Human, content: 'first question', id: 'human-1' },
                { type: AssistantMessageType.Assistant, content: 'first answer', id: 'assistant-1' },
            ]
            logic.unmount()
            const getSpy = jest.spyOn(api.conversations, 'get').mockResolvedValue({
                ...MOCK_IN_PROGRESS_CONVERSATION,
                messages: loadedMessages,
            } as ConversationDetail)
            const streamSpy = mockStream()

            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: {
                    // No messages field — simulates a list-level cache entry for an in-progress chat.
                    ...MOCK_IN_PROGRESS_CONVERSATION,
                } as ConversationDetail,
            })
            logic.mount()
            // Drain pending microtasks/timers so the async afterMount runs to completion.
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(getSpy).toHaveBeenCalledWith(MOCK_CONVERSATION_ID)
            // The loaded history must be present in threadRaw — proving setThread ran.
            expect(logic.values.threadRaw).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ id: 'human-1', content: 'first question', status: 'completed' }),
                    expect.objectContaining({ id: 'assistant-1', content: 'first answer', status: 'completed' }),
                ])
            )
            // And reconnectToStream must have fired — proving the load-then-reconnect flow ran
            // end to end, not just the load.
            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({ conversation: MOCK_CONVERSATION_ID, content: null }),
                expect.any(Object)
            )
        })

        it('does not fetch or reconnect when mounted for a new chat', async () => {
            // parentConversationId (from maxLogic.conversationId) is the real signal for "existing
            // backend conversation". The local maxThreadLogic.conversationId selector falls back
            // to the frontend-generated UUID, so gating on it would fire loadConversation on every
            // new chat and 404.
            logic.unmount()
            maxLogicInstance.actions.startNewConversation()
            const getSpy = jest.spyOn(api.conversations, 'get')
            const streamSpy = mockStream()

            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
            logic.mount()
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(getSpy).not.toHaveBeenCalled()
            expect(streamSpy).not.toHaveBeenCalled()
        })

        it('updates threadRaw with status fields when conversation prop changes with new messages', async () => {
            // Start with empty conversation
            const initialConversation: ConversationDetail = {
                id: MOCK_CONVERSATION_ID,
                status: ConversationStatus.Idle,
                title: 'Test conversation',
                user: MOCK_DEFAULT_BASIC_USER,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                messages: [],
                type: ConversationType.Assistant,
            }

            logic.unmount()
            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: initialConversation,
            })
            logic.mount()

            // Verify initial state
            expect(logic.values.threadRaw).toEqual([])

            // Update conversation with new messages via prop change
            const updatedConversation: ConversationDetail = {
                ...initialConversation,
                messages: [
                    {
                        type: AssistantMessageType.Human,
                        content: 'New question',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'New response',
                        id: 'assistant-1',
                    },
                ],
            }

            // Simulate prop change by creating new logic instance with updated conversation
            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: updatedConversation,
            })
            logic.mount()

            // Check that threadRaw now has messages with status fields
            expect(logic.values.threadRaw).toEqual([
                {
                    type: AssistantMessageType.Human,
                    content: 'New question',
                    id: 'human-1',
                    status: 'completed',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'New response',
                    id: 'assistant-1',
                    status: 'completed',
                },
            ])
        })
    })

    describe('sandbox history-load branch', () => {
        const SANDBOX_TASK_ID = 'task-abc'
        const SANDBOX_RUN_ID = 'run-abc'

        function sandboxConversation(currentRunId: string | null): ConversationDetail {
            return {
                id: MOCK_CONVERSATION_ID,
                status: ConversationStatus.InProgress,
                title: 'Sandbox chat',
                user: MOCK_DEFAULT_BASIC_USER,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                type: ConversationType.Assistant,
                agent_runtime: 'sandbox',
                task: { id: SANDBOX_TASK_ID, latest_run: currentRunId },
                messages: [],
            }
        }

        it('replays logs/ then opens SSE for a non-terminal sandbox run, never reconnecting LangGraph', async () => {
            logic.unmount()
            jest.spyOn(api.conversations, 'get').mockResolvedValue(sandboxConversation(SANDBOX_RUN_ID))
            const logsSpy = jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([])
            const runSpy = jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)
            const streamSpy = mockStream()

            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: sandboxConversation(SANDBOX_RUN_ID),
            })
            logic.mount()
            // Drain the async afterMount (loadConversation → bootstrapRun → logs/ replay → run refetch).
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))

            // bootstrapRun replayed logs/ and refetched the run, then opened SSE — and the LangGraph
            // stream was never touched (coexistence).
            expect(logsSpy).toHaveBeenCalledWith(SANDBOX_TASK_ID, SANDBOX_RUN_ID)
            expect(runSpy).toHaveBeenCalledWith(SANDBOX_TASK_ID, SANDBOX_RUN_ID)
            expect(streamSpy).not.toHaveBeenCalled()
        })

        it('does not bootstrap a sandbox run without a latest_run', async () => {
            logic.unmount()
            jest.spyOn(api.conversations, 'get').mockResolvedValue(sandboxConversation(null))
            const logsSpy = jest.spyOn(api.tasks.runs, 'getLogEntries')
            const streamSpy = mockStream()

            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: sandboxConversation(null),
            })
            logic.mount()
            await new Promise((resolve) => setTimeout(resolve, 0))

            expect(logsSpy).not.toHaveBeenCalled()
            expect(streamSpy).not.toHaveBeenCalled()
        })
    })

    describe('sandbox prewarm', () => {
        const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

        function idleSandboxConversation(): ConversationDetail {
            return {
                id: MOCK_CONVERSATION_ID,
                status: ConversationStatus.Idle,
                title: 'Sandbox chat',
                user: MOCK_DEFAULT_BASIC_USER,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                type: ConversationType.Assistant,
                agent_runtime: 'sandbox',
                task: { id: 'task-1', latest_run: null },
                messages: [],
            }
        }

        async function mountIdleSandbox(): Promise<void> {
            logic.unmount()
            jest.spyOn(api.conversations, 'get').mockResolvedValue(idleSandboxConversation())
            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                panelId: 'test',
                conversation: idleSandboxConversation(),
            })
            logic.mount()
            await flush()
        }

        const warmHandle = {
            task_id: 'task-1',
            run_id: 'run-1',
            trace_id: null,
            run_status: 'in_progress' as const,
            just_created_run: true,
        }

        it('releases a warm sandbox abandoned while the warm POST was still in flight', async () => {
            await mountIdleSandbox()

            // Warm = open with content: null. Keep the POST in flight so the abandon races it.
            let resolvePrewarm: (handle: typeof warmHandle) => void = () => {}
            const openSpy = jest
                .spyOn(api.conversations, 'open')
                .mockReturnValue(new Promise<typeof warmHandle>((resolve) => (resolvePrewarm = resolve)) as any)

            logic.actions.prewarmSandbox()
            await flush()
            expect(openSpy).toHaveBeenCalledWith(MOCK_CONVERSATION_ID, {
                content: null,
                initial_permission_mode: 'auto',
            })

            // User abandons the input before the warm resolves — nothing is warm yet, so the release
            // is deferred (pendingRelease), not dropped, and no cancel fires.
            await expectLogic(logic, () => {
                logic.actions.releaseSandboxPrewarm()
            }).toNotHaveDispatchedActions(['cancelSandboxRun'])
            await flush()

            // The warm POST resolves — the deferred release fires cancelSandboxRun so the sandbox
            // isn't leaked.
            await expectLogic(logic, () => {
                resolvePrewarm(warmHandle)
            }).toDispatchActions(['cancelSandboxRun'])
        })

        it('does not release a warm that resolved with no pending abandon', async () => {
            await mountIdleSandbox()

            jest.spyOn(api.conversations, 'open').mockResolvedValue(warmHandle)

            await expectLogic(logic, () => {
                logic.actions.prewarmSandbox()
            }).toNotHaveDispatchedActions(['cancelSandboxRun'])
            await flush()
            await flush()
        })
    })

    describe('filteredCommands runtime filter', () => {
        function setRuntime(runtime: 'langgraph' | 'sandbox'): void {
            logic.actions.setConversation({
                ...MOCK_IN_PROGRESS_CONVERSATION,
                status: ConversationStatus.Idle,
                agent_runtime: runtime,
            } as Conversation)
            // Empty question matches every command by prefix.
            maxLogicInstance.actions.setQuestion('')
        }

        it('hides /init and /remember for sandbox conversations, keeps /usage and /feedback', async () => {
            setRuntime('sandbox')
            const names = logic.values.filteredCommands.map((c) => c.name)
            expect(names).not.toContain(SlashCommandName.SlashInit)
            expect(names).not.toContain(SlashCommandName.SlashRemember)
            expect(names).toContain(SlashCommandName.SlashUsage)
            expect(names).toContain(SlashCommandName.SlashFeedback)
            // /ticket must be offered even when no billing context is available — the backend decides eligibility
            expect(names).toContain(SlashCommandName.SlashTicket)
        })

        it('keeps the full command set for langgraph conversations', async () => {
            setRuntime('langgraph')
            const names = logic.values.filteredCommands.map((c) => c.name)
            expect(names).toContain(SlashCommandName.SlashInit)
            expect(names).toContain(SlashCommandName.SlashRemember)
            expect(names).toContain(SlashCommandName.SlashUsage)
            expect(names).toContain(SlashCommandName.SlashFeedback)
            expect(names).toContain(SlashCommandName.SlashTicket)
        })
    })

    describe('command selection and activation', () => {
        beforeEach(() => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
            logic.mount()
        })

        it('selectCommand sets question for command without arg', async () => {
            const initCommand = {
                name: SlashCommandName.SlashInit,
                description: 'Test command',
                icon: React.createElement('div'),
            }

            await expectLogic(logic, () => {
                logic.actions.selectCommand(initCommand)
            }).toDispatchActions(['setQuestion'])

            expect(logic.values.question).toBe('/init')
        })

        it('selectCommand sets question with space for command with arg', async () => {
            const rememberCommand = {
                name: SlashCommandName.SlashRemember,
                arg: '[information]' as const,
                description: 'Test command with arg',
                icon: React.createElement('div'),
            }

            await expectLogic(logic, () => {
                logic.actions.selectCommand(rememberCommand)
            }).toDispatchActions(['setQuestion'])

            expect(logic.values.question).toBe('/remember ')
        })

        it('activateCommand calls askMax directly for command without arg', async () => {
            const initCommand = {
                name: SlashCommandName.SlashInit,
                description: 'Test command',
                icon: React.createElement('div'),
            }

            const askMaxSpy = jest.spyOn(logic.actions, 'askMax')

            logic.actions.activateCommand(initCommand)

            expect(askMaxSpy).toHaveBeenCalledWith('/init')
        })

        it('activateCommand sets question for command with arg', async () => {
            const rememberCommand = {
                name: SlashCommandName.SlashRemember,
                arg: '[information]' as const,
                description: 'Test command with arg',
                icon: React.createElement('div'),
            }

            await expectLogic(logic, () => {
                logic.actions.activateCommand(rememberCommand)
            }).toDispatchActions(['setQuestion'])

            expect(logic.values.question).toBe('/remember ')
        })

        it('activateCommand does not call askMax for command with arg, only setQuestion', async () => {
            const rememberCommand = {
                name: SlashCommandName.SlashRemember,
                arg: '[information]' as const,
                description: 'Test command with arg',
                icon: React.createElement('div'),
            }

            const askMaxSpy = jest.spyOn(logic.actions, 'askMax')
            const setQuestionSpy = jest.spyOn(logic.actions, 'setQuestion')

            logic.actions.activateCommand(rememberCommand)

            expect(askMaxSpy).not.toHaveBeenCalled()
            expect(setQuestionSpy).toHaveBeenCalledWith('/remember ')
            expect(logic.values.question).toBe('/remember ')
        })
    })

    describe('assistant update event handling', () => {
        beforeEach(() => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
            logic.mount()
        })

        it('setToolCallUpdate adds update to toolCallUpdateMap', async () => {
            const updateEvent = {
                id: 'update-1',
                tool_call_id: 'tool-call-123',
                content: 'Processing data...',
            }

            await expectLogic(logic, () => {
                logic.actions.setToolCallUpdate(updateEvent, {})
            })

            expect(logic.values.toolCallUpdateMap.get('tool-call-123')).toEqual(['Processing data...'])
        })

        it('setToolCallUpdate adds multiple updates for same tool call', async () => {
            const toolCallId = 'tool-call-123'

            await expectLogic(logic, () => {
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-1',
                        tool_call_id: toolCallId,
                        content: 'Step 1 complete',
                    },
                    {}
                )
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-2',
                        tool_call_id: toolCallId,
                        content: 'Step 2 complete',
                    },
                    {}
                )
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-3',
                        tool_call_id: toolCallId,
                        content: 'Step 3 complete',
                    },
                    {}
                )
            })

            expect(logic.values.toolCallUpdateMap.get(toolCallId)).toEqual([
                'Step 1 complete',
                'Step 2 complete',
                'Step 3 complete',
            ])
        })

        it('setToolCallUpdate ignores duplicate updates', async () => {
            const toolCallId = 'tool-call-123'
            const sameContent = 'Same update'

            await expectLogic(logic, () => {
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-1',
                        tool_call_id: toolCallId,
                        content: sameContent,
                    },
                    {}
                )
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-2',
                        tool_call_id: toolCallId,
                        content: sameContent,
                    },
                    {}
                )
            })

            // Should only have one entry despite two calls
            expect(logic.values.toolCallUpdateMap.get(toolCallId)).toEqual([sameContent])
        })

        it('setToolCallUpdate handles updates for different tool calls', async () => {
            await expectLogic(logic, () => {
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-1',
                        tool_call_id: 'tool-1',
                        content: 'Tool 1 update',
                    },
                    {}
                )
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-2',
                        tool_call_id: 'tool-2',
                        content: 'Tool 2 update',
                    },
                    {}
                )
            })

            expect(logic.values.toolCallUpdateMap.get('tool-1')).toEqual(['Tool 1 update'])
            expect(logic.values.toolCallUpdateMap.get('tool-2')).toEqual(['Tool 2 update'])
        })

        it('update messages are excluded from threadGrouped', async () => {
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
                        content: 'response',
                        status: 'completed',
                        id: 'assistant-1',
                    },
                ])
                // UpdateMessages should not appear in thread directly
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-1',
                        tool_call_id: 'tool-call-123',
                        content: 'This should not appear',
                    },
                    {}
                )
            }).toMatchValues({
                threadGrouped: [
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'response',
                        status: 'completed',
                        id: 'assistant-1',
                    },
                ],
            })
        })
    })

    describe('onEventImplementation message streaming', () => {
        beforeEach(() => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
            logic.mount()
        })

        it('handles streaming message with temp- ID by adding it first time', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            await expectLogic(logic, async () => {
                // Start with a human message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'human-1',
                        type: AssistantMessageType.Human,
                        content: 'User question',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Assistant responds with temp ID
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'Partial response',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            expect(logic.values.threadRaw).toEqual([
                {
                    id: 'human-1',
                    type: AssistantMessageType.Human,
                    content: 'User question',
                    status: 'completed',
                },
                {
                    id: 'temp-0',
                    type: AssistantMessageType.Assistant,
                    content: 'Partial response',
                    status: 'loading',
                },
            ])
        })

        it('handles streaming message with temp- ID by replacing it on subsequent updates', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            await expectLogic(logic, async () => {
                // Start with a human message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'human-1',
                        type: AssistantMessageType.Human,
                        content: 'User question',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // First streaming chunk
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'Partial',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Second streaming chunk updates the same temp message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'Partial response updated',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            expect(logic.values.threadRaw).toEqual([
                {
                    id: 'human-1',
                    type: AssistantMessageType.Human,
                    content: 'User question',
                    status: 'completed',
                },
                {
                    id: 'temp-0',
                    type: AssistantMessageType.Assistant,
                    content: 'Partial response updated',
                    status: 'loading',
                },
            ])
        })

        it('handles multiple streaming messages with different temp IDs (web search scenario)', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            await expectLogic(logic, async () => {
                // Human asks a question
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'human-1',
                        type: AssistantMessageType.Human,
                        content: 'What is the latest on topic X?',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // First assistant message starts
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'First message',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Web search happens, new message starts
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-1',
                        type: AssistantMessageType.Assistant,
                        content: 'Second message after web search',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            expect(logic.values.threadRaw).toEqual([
                {
                    id: 'human-1',
                    type: AssistantMessageType.Human,
                    content: 'What is the latest on topic X?',
                    status: 'completed',
                },
                {
                    id: 'temp-0',
                    type: AssistantMessageType.Assistant,
                    content: 'First message',
                    status: 'loading',
                },
                {
                    id: 'temp-1',
                    type: AssistantMessageType.Assistant,
                    content: 'Second message after web search',
                    status: 'loading',
                },
            ])
        })

        it('finalizes message by replacing temp message with final UUID', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            await expectLogic(logic, async () => {
                // Human message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'human-1',
                        type: AssistantMessageType.Human,
                        content: 'User question',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Start with temp message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'Streaming...',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Finalize with real UUID
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: '550e8400-e29b-41d4-a716-446655440000',
                        type: AssistantMessageType.Assistant,
                        content: 'Complete response',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            expect(logic.values.threadRaw).toEqual([
                {
                    id: 'human-1',
                    type: AssistantMessageType.Human,
                    content: 'User question',
                    status: 'completed',
                },
                {
                    id: '550e8400-e29b-41d4-a716-446655440000',
                    type: AssistantMessageType.Assistant,
                    content: 'Complete response',
                    status: 'completed',
                },
            ])
        })

        it('finalizes multiple messages from web search generation', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            await expectLogic(logic, async () => {
                // Human asks a question
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'human-1',
                        type: AssistantMessageType.Human,
                        content: 'What are the latest developments?',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // First temp message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'First part',
                        meta: { thinking: [{ type: 'thinking', thinking: 'Processing' }] },
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Second temp message (after web search)
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-1',
                        type: AssistantMessageType.Assistant,
                        content: 'Second part',
                        meta: {
                            thinking: [
                                { type: 'server_tool_use', name: 'web_search' },
                                { type: 'web_search_tool_result', content: 'Search results' },
                            ],
                        },
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            // At this point we should have human message + 2 temp messages
            expect(logic.values.threadRaw).toHaveLength(3)
            expect(logic.values.threadRaw[0].id).toBe('human-1')
            expect(logic.values.threadRaw[1].id).toBe('temp-0')
            expect(logic.values.threadRaw[2].id).toBe('temp-1')

            await expectLogic(logic, async () => {
                // Finalize first message - replaces first temp message (index 1)
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'uuid-1',
                        type: AssistantMessageType.Assistant,
                        content: 'First part finalized',
                        meta: { thinking: [{ type: 'thinking', thinking: 'Processing' }] },
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            // Human message + first finalized + second still temp
            expect(logic.values.threadRaw).toEqual([
                {
                    id: 'human-1',
                    type: AssistantMessageType.Human,
                    content: 'What are the latest developments?',
                    status: 'completed',
                },
                {
                    id: 'uuid-1',
                    type: AssistantMessageType.Assistant,
                    content: 'First part finalized',
                    meta: { thinking: [{ type: 'thinking', thinking: 'Processing' }] },
                    status: 'completed',
                },
                {
                    id: 'temp-1',
                    type: AssistantMessageType.Assistant,
                    content: 'Second part',
                    meta: {
                        thinking: [
                            { type: 'server_tool_use', name: 'web_search' },
                            { type: 'web_search_tool_result', content: 'Search results' },
                        ],
                    },
                    status: 'loading',
                },
            ])

            await expectLogic(logic, async () => {
                // Finalize second message - replaces second temp message (index 2)
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'uuid-2',
                        type: AssistantMessageType.Assistant,
                        content: 'Second part finalized',
                        meta: {
                            thinking: [
                                { type: 'server_tool_use', name: 'web_search' },
                                { type: 'web_search_tool_result', content: 'Search results' },
                            ],
                        },
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            // All messages finalized
            expect(logic.values.threadRaw).toEqual([
                {
                    id: 'human-1',
                    type: AssistantMessageType.Human,
                    content: 'What are the latest developments?',
                    status: 'completed',
                },
                {
                    id: 'uuid-1',
                    type: AssistantMessageType.Assistant,
                    content: 'First part finalized',
                    meta: { thinking: [{ type: 'thinking', thinking: 'Processing' }] },
                    status: 'completed',
                },
                {
                    id: 'uuid-2',
                    type: AssistantMessageType.Assistant,
                    content: 'Second part finalized',
                    meta: {
                        thinking: [
                            { type: 'server_tool_use', name: 'web_search' },
                            { type: 'web_search_tool_result', content: 'Search results' },
                        ],
                    },
                    status: 'completed',
                },
            ])
        })

        it('handles message without ID by adding it when finalized', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            await expectLogic(logic, async () => {
                // Human message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'human-1',
                        type: AssistantMessageType.Human,
                        content: 'User question',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Message without ID should be added as loading
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        type: AssistantMessageType.Assistant,
                        content: 'Streaming without ID',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            expect(logic.values.threadRaw).toEqual([
                {
                    id: 'human-1',
                    type: AssistantMessageType.Human,
                    content: 'User question',
                    status: 'completed',
                },
                {
                    type: AssistantMessageType.Assistant,
                    content: 'Streaming without ID',
                    status: 'loading',
                },
            ])
        })

        it('replaces existing message when final ID matches already present ID', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            const finalId = 'uuid-final'

            await expectLogic(logic, async () => {
                // Human message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'human-1',
                        type: AssistantMessageType.Human,
                        content: 'User question',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Add a message with final ID
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: finalId,
                        type: AssistantMessageType.Assistant,
                        content: 'First version',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )

                // Update the same message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: finalId,
                        type: AssistantMessageType.Assistant,
                        content: 'Updated version',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            expect(logic.values.threadRaw).toEqual([
                {
                    id: 'human-1',
                    type: AssistantMessageType.Human,
                    content: 'User question',
                    status: 'completed',
                },
                {
                    id: finalId,
                    type: AssistantMessageType.Assistant,
                    content: 'Updated version',
                    status: 'completed',
                },
            ])
        })

        it('handles conversation event by setting conversation', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            const newConversation = {
                id: 'new-conv-id',
                status: ConversationStatus.InProgress,
                title: '',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                type: ConversationType.Assistant,
            }

            await expectLogic(logic, async () => {
                await onEventImplementation(AssistantEventType.Conversation, JSON.stringify(newConversation), {
                    actions: logic.actions,
                    values: logic.values,
                    props: logic.props,
                    agentMode: null,
                    cache: {},
                })
            })

            expect(logic.values.conversation).toEqual({
                ...newConversation,
                agent_mode: null,
                title: 'New chat', // Default title
            })
        })

        it('handles status event with generation error', async () => {
            const { onEventImplementation } = await import('./maxThreadLogic')

            await expectLogic(logic, async () => {
                // Add a message first
                logic.actions.addMessage({
                    id: 'msg-1',
                    type: AssistantMessageType.Assistant,
                    content: 'Failed message',
                    status: 'loading',
                })

                // Trigger error status
                await onEventImplementation(
                    AssistantEventType.Status,
                    JSON.stringify({
                        type: 'generation_error',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props, agentMode: null, cache: {} }
                )
            })

            expect(logic.values.threadRaw[logic.values.threadRaw.length - 1].status).toBe('error')
        })
    })

    describe('enhanceThreadToolCalls', () => {
        beforeEach(() => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
            logic.mount()
        })

        it('marks tool call as completed when corresponding tool call message exists', async () => {
            const toolCallId = 'tool-123'

            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Using tool',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: toolCallId,
                                name: 'test_tool',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                    {
                        type: AssistantMessageType.ToolCall,
                        content: 'Tool completed successfully',
                        status: 'completed',
                        id: 'tool-msg-1',
                        tool_call_id: toolCallId,
                        ui_payload: {},
                    },
                ])
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            expect(enhancedToolCalls).toBeTruthy()
            expect(enhancedToolCalls?.[0].status).toBe('completed')
        })

        it('marks tool call as in_progress when no completion message and still loading', async () => {
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, panelId: 'test' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Using tool',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: 'tool-123',
                                name: 'test_tool',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            expect(enhancedToolCalls?.[0].status).toBe('in_progress')
        })

        it('marks tool call as failed when no completion and not loading', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Using tool',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: 'tool-123',
                                name: 'test_tool',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            expect(enhancedToolCalls?.[0].status).toBe('failed')
        })

        it('attaches updates from toolCallUpdateMap to tool calls', async () => {
            const toolCallId = 'tool-123'

            await expectLogic(logic, () => {
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-1',
                        tool_call_id: toolCallId,
                        content: 'Progress update 1',
                    },
                    {}
                )
                logic.actions.setToolCallUpdate(
                    {
                        id: 'update-2',
                        tool_call_id: toolCallId,
                        content: 'Progress update 2',
                    },
                    {}
                )
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Using tool',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: toolCallId,
                                name: 'test_tool',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            expect(enhancedToolCalls?.[0].updates).toEqual(['Progress update 1', 'Progress update 2'])
        })

        it('marks last todo_write tool call with isLastPlanningMessage', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Planning',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: 'todo-1',
                                name: 'todo_write',
                                args: { todos: [] },
                                type: 'tool_call',
                            },
                        ],
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'More planning',
                        status: 'completed',
                        id: 'assistant-2',
                        tool_calls: [
                            {
                                id: 'todo-2',
                                name: 'todo_write',
                                args: { todos: [] },
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
            })

            const firstToolCall = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls?.[0] as EnhancedToolCall
            const secondToolCall = (logic.values.threadGrouped[1] as AssistantMessage)
                .tool_calls?.[0] as EnhancedToolCall

            expect(firstToolCall?.isLastPlanningMessage).toBeFalsy()
            expect(secondToolCall?.isLastPlanningMessage).toBeTruthy()
        })

        it('handles multiple tool calls in single message', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Using multiple tools',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: 'tool-1',
                                name: 'tool_one',
                                args: {},
                                type: 'tool_call',
                            },
                            {
                                id: 'tool-2',
                                name: 'tool_two',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                    {
                        type: AssistantMessageType.ToolCall,
                        content: 'Tool 1 complete',
                        status: 'completed',
                        id: 'tool-msg-1',
                        tool_call_id: 'tool-1',
                        ui_payload: {},
                    },
                ])
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            expect(enhancedToolCalls?.[0].status).toBe('completed')
            expect(enhancedToolCalls?.[1].status).toBe('failed') // No completion message
        })

        it('handles tool calls with empty updates array', async () => {
            const toolCallId = 'tool-123'

            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Using tool',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: toolCallId,
                                name: 'test_tool',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            expect(enhancedToolCalls?.[0].updates).toEqual([])
        })

        it('marks tool call as failed when approval is rejected', async () => {
            const toolCallId = 'tool-123'
            const proposalId = 'proposal-123'

            await expectLogic(logic, () => {
                // Set up a tool call
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Dangerous operation',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: toolCallId,
                                name: 'dangerous_tool',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                    // Tool call result message exists (operation was "completed" but later rejected)
                    {
                        type: AssistantMessageType.ToolCall,
                        content: 'Tool executed',
                        status: 'completed',
                        id: 'tool-msg-1',
                        tool_call_id: toolCallId,
                        ui_payload: {},
                    },
                ])
                // Set up pending approval that was rejected
                logic.actions.addPendingApprovalData({
                    proposal_id: proposalId,
                    original_tool_call_id: toolCallId,
                    tool_name: 'dangerous_tool',
                    decision_status: 'pending',
                    preview: 'Preview text',
                    payload: {},
                })
                // Resolve the approval as rejected
                logic.actions.setResolvedApprovalStatus(proposalId, 'rejected')
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            // Even though there's a result message, rejected approval should mark it as failed
            expect(enhancedToolCalls?.[0].status).toBe('failed')
        })

        it('marks tool call as failed when approval is auto_rejected', async () => {
            const toolCallId = 'tool-456'
            const proposalId = 'proposal-456'

            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Dangerous operation',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: toolCallId,
                                name: 'dangerous_tool',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
                logic.actions.addPendingApprovalData({
                    proposal_id: proposalId,
                    original_tool_call_id: toolCallId,
                    tool_name: 'dangerous_tool',
                    decision_status: 'pending',
                    preview: 'Preview text',
                    payload: {},
                })
                logic.actions.setResolvedApprovalStatus(proposalId, 'auto_rejected')
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            expect(enhancedToolCalls?.[0].status).toBe('failed')
        })

        it('marks tool call as completed when approval is approved', async () => {
            const toolCallId = 'tool-789'
            const proposalId = 'proposal-789'

            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Dangerous operation',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: toolCallId,
                                name: 'dangerous_tool',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                    {
                        type: AssistantMessageType.ToolCall,
                        content: 'Tool executed',
                        status: 'completed',
                        id: 'tool-msg-1',
                        tool_call_id: toolCallId,
                        ui_payload: {},
                    },
                ])
                logic.actions.addPendingApprovalData({
                    proposal_id: proposalId,
                    original_tool_call_id: toolCallId,
                    tool_name: 'dangerous_tool',
                    decision_status: 'pending',
                    preview: 'Preview text',
                    payload: {},
                })
                logic.actions.setResolvedApprovalStatus(proposalId, 'approved')
            })

            const enhancedToolCalls = (logic.values.threadGrouped[0] as AssistantMessage)
                .tool_calls as EnhancedToolCall[]
            // Approved operations should show as completed
            expect(enhancedToolCalls?.[0].status).toBe('completed')
        })
    })

    describe('retryCount', () => {
        it('starts at 0', () => {
            expect(logic.values.retryCount).toBe(0)
        })

        it('increments on retryLastMessage', async () => {
            await expectLogic(logic, () => {
                logic.actions.retryLastMessage()
            }).toMatchValues({
                retryCount: 1,
            })
        })

        it('increments multiple times', async () => {
            logic.actions.retryLastMessage()
            logic.actions.retryLastMessage()

            await expectLogic(logic, () => {
                logic.actions.retryLastMessage()
            }).toMatchValues({
                retryCount: 3,
            })
        })

        it('resets to 0 on resetRetryCount', async () => {
            logic.actions.retryLastMessage()
            logic.actions.retryLastMessage()

            await expectLogic(logic, () => {
                logic.actions.resetRetryCount()
            }).toMatchValues({
                retryCount: 0,
            })
        })

        it('resets to 0 on resetThread', async () => {
            logic.actions.retryLastMessage()
            logic.actions.retryLastMessage()

            await expectLogic(logic, () => {
                logic.actions.resetThread()
            }).toMatchValues({
                retryCount: 0,
            })
        })
    })

    describe('finalizeStreamingMessages', () => {
        it('removes streaming messages so server becomes source of truth', async () => {
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
                        content: 'partial response',
                        status: 'loading',
                        // no id - streaming message
                    },
                ])
                logic.actions.finalizeStreamingMessages()
            })

            // Streaming message should be removed
            expect(logic.values.threadRaw.length).toBe(1)
            // Completed message should be unchanged
            expect(logic.values.threadRaw[0].id).toBe('human-1')
            expect(logic.values.threadRaw[0].status).toBe('completed')
        })

        it('does not modify already completed messages', async () => {
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
                        content: 'complete response',
                        status: 'completed',
                        id: 'assistant-1',
                    },
                ])
                logic.actions.finalizeStreamingMessages()
            })

            // Messages should be unchanged
            expect(logic.values.threadRaw[0].id).toBe('human-1')
            expect(logic.values.threadRaw[1].id).toBe('assistant-1')
        })

        it('removes all streaming messages', async () => {
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
                        content: 'streaming assistant',
                        status: 'loading',
                    },
                    {
                        type: AssistantMessageType.Artifact,
                        content: {},
                        status: 'loading',
                        artifact_id: 'artifact-1',
                        source: 'artifact',
                    } as any,
                ])
                logic.actions.finalizeStreamingMessages()
            })

            // Both streaming messages should be removed
            expect(logic.values.threadRaw.length).toBe(1)
            expect(logic.values.threadRaw[0].id).toBe('human-1')
        })

        it('allows new streaming messages after finalization', async () => {
            await expectLogic(logic, () => {
                // Set up a thread with a streaming message
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'partial response before error',
                        status: 'loading',
                    },
                ])
                // Finalize it (simulating error handling - removes streaming messages)
                logic.actions.finalizeStreamingMessages()
            })

            // Streaming message should be removed
            expect(logic.values.threadRaw.length).toBe(1)

            // Now simulate a new streaming message coming in after retry
            await expectLogic(logic, () => {
                logic.actions.addMessage({
                    type: AssistantMessageType.Assistant,
                    content: 'new streaming response',
                    status: 'loading',
                })
            })

            // Should have 2 messages now - the new streaming message is added
            expect(logic.values.threadRaw.length).toBe(2)
            expect(logic.values.threadRaw[0].id).toBe('human-1')
            expect(logic.values.threadRaw[1].status).toBe('loading')
            expect((logic.values.threadRaw[1] as AssistantMessage).content).toBe('new streaming response')
        })
    })

    describe('cancelCount', () => {
        it('starts at 0', () => {
            expect(logic.values.cancelCount).toBe(0)
        })

        it('increments on stopGeneration', async () => {
            await expectLogic(logic, () => {
                logic.actions.stopGeneration()
            }).toMatchValues({
                cancelCount: 1,
            })
        })

        it('increments multiple times', async () => {
            logic.actions.stopGeneration()
            logic.actions.stopGeneration()

            await expectLogic(logic, () => {
                logic.actions.stopGeneration()
            }).toMatchValues({
                cancelCount: 3,
            })
        })

        it('resets to 0 on resetCancelCount', async () => {
            logic.actions.stopGeneration()
            logic.actions.stopGeneration()

            await expectLogic(logic, () => {
                logic.actions.resetCancelCount()
            }).toMatchValues({
                cancelCount: 0,
            })
        })

        it('resets to 0 on resetThread', async () => {
            logic.actions.stopGeneration()
            logic.actions.stopGeneration()

            await expectLogic(logic, () => {
                logic.actions.resetThread()
            }).toMatchValues({
                cancelCount: 0,
            })
        })
    })

    describe('stopGeneration button state (LangGraph cancel race)', () => {
        it('clears all loading flags after a successful cancel so the stop button returns to send', async () => {
            jest.spyOn(api.conversations, 'cancel').mockResolvedValue(undefined)

            // An in-progress conversation drives conversationLoading -> true
            logic.actions.setConversation(MOCK_IN_PROGRESS_CONVERSATION)
            await expectLogic(logic).toMatchValues({ conversationLoading: true })

            await expectLogic(logic, () => {
                logic.actions.stopGeneration()
            }).toDispatchActions(['stopGeneration', 'setConversation', 'setCancelLoading'])

            expect(logic.values.conversationLoading).toBe(false)
            expect(logic.values.streamingActive).toBe(false)
            expect(logic.values.threadLoading).toBe(false)
            expect(logic.values.cancelLoading).toBe(false)
        })
    })

    describe('multiQuestionFormPending selector', () => {
        it('returns true when thread ends with AssistantMessage containing create_form tool call', async () => {
            // With NodeInterrupt(None), no ToolCall message is created - the thread ends with the AssistantMessage
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Human,
                        content: 'Hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Please answer these questions:',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: 'create-form-tc-1',
                                name: 'create_form',
                                args: { questions: [{ id: 'q1', question: 'What is your name?' }] },
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
            }).toMatchValues({
                multiQuestionFormPending: true,
            })
        })

        it('returns false when thread is empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([])
            }).toMatchValues({
                multiQuestionFormPending: false,
            })
        })

        it('returns false when last message is a ToolCall response (not a create_form tool call)', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Human,
                        content: 'Hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Using a different tool',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: 'other-tool-tc-1',
                                name: 'search',
                                args: {},
                                type: 'tool_call',
                            },
                        ],
                    },
                    {
                        type: AssistantMessageType.ToolCall,
                        content: 'Search results',
                        status: 'completed',
                        id: 'tool-msg-1',
                        tool_call_id: 'other-tool-tc-1',
                        ui_payload: { search: {} },
                    },
                ])
            }).toMatchValues({
                multiQuestionFormPending: false,
            })
        })

        it('returns false when last message is an assistant message without tool calls', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Human,
                        content: 'Hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Thanks for your answers!',
                        status: 'completed',
                        id: 'assistant-1',
                    },
                ])
            }).toMatchValues({
                multiQuestionFormPending: false,
            })
        })
    })

    describe('submissionDisabledReason selector', () => {
        it('returns "Please answer, skip, or dismiss the form above" when multiQuestionFormPending is true', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Please answer:',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: 'create-form-tc-1',
                                name: 'create_form',
                                args: { questions: [] },
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
            }).toMatchValues({
                submissionDisabledReason: 'Please answer, skip, or dismiss the form above',
            })
        })
    })

    describe('inputDisabled selector', () => {
        it('returns true when multiQuestionFormPending is true', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'Please answer:',
                        status: 'completed',
                        id: 'assistant-1',
                        tool_calls: [
                            {
                                id: 'create-form-tc-1',
                                name: 'create_form',
                                args: { questions: [] },
                                type: 'tool_call',
                            },
                        ],
                    },
                ])
            }).toMatchValues({
                inputDisabled: true,
            })
        })
    })

    describe('agent mode functionality', () => {
        beforeEach(() => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
            logic.mount()
        })

        it('setAgentMode sets the agent mode', async () => {
            await expectLogic(logic, () => {
                logic.actions.setAgentMode(AgentMode.SQL)
            }).toMatchValues({
                agentMode: AgentMode.SQL,
            })
        })

        it('setAgentMode locks the agent mode by user', async () => {
            expect(logic.values.agentModeLockedByUser).toBe(false)

            await expectLogic(logic, () => {
                logic.actions.setAgentMode(AgentMode.ProductAnalytics)
            }).toMatchValues({
                agentModeLockedByUser: true,
            })
        })

        it('syncAgentModeFromConversation sets agent mode without locking', async () => {
            await expectLogic(logic, () => {
                logic.actions.syncAgentModeFromConversation(AgentMode.SessionReplay)
            }).toMatchValues({
                agentMode: AgentMode.SessionReplay,
                agentModeLockedByUser: false,
            })
        })

        it('askMax resets agentModeLockedByUser', async () => {
            mockStream()

            logic.actions.setAgentMode(AgentMode.SQL)
            expect(logic.values.agentModeLockedByUser).toBe(true)

            await expectLogic(logic, () => {
                logic.actions.askMax('test')
            }).toMatchValues({
                agentModeLockedByUser: false,
            })
        })

        it('setConversation syncs agent mode when not locked by user', async () => {
            const conversationWithAgentMode: Conversation = {
                ...MOCK_CONVERSATION,
                agent_mode: AgentMode.ProductAnalytics,
            }

            await expectLogic(logic, () => {
                logic.actions.setConversation(conversationWithAgentMode)
            }).toMatchValues({
                agentMode: AgentMode.ProductAnalytics,
            })
        })

        it('setConversation does not sync agent mode when locked by user', async () => {
            logic.actions.setAgentMode(AgentMode.SQL)
            expect(logic.values.agentModeLockedByUser).toBe(true)

            const conversationWithAgentMode: Conversation = {
                ...MOCK_CONVERSATION,
                agent_mode: AgentMode.ProductAnalytics,
            }

            await expectLogic(logic, () => {
                logic.actions.setConversation(conversationWithAgentMode)
            }).toMatchValues({
                agentMode: AgentMode.SQL, // Should remain SQL, not switch to ProductAnalytics
            })
        })

        it('askMax includes agent_mode in stream data', async () => {
            const streamSpy = mockStream()

            logic.actions.setAgentMode(AgentMode.SQL)

            await expectLogic(logic, () => {
                logic.actions.askMax('test prompt')
            })

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    content: 'test prompt',
                    agent_mode: AgentMode.SQL,
                }),
                expect.any(Object)
            )
        })

        it('reconnectToStream includes current agent mode', async () => {
            const streamSpy = mockStream()

            logic.actions.setAgentMode(AgentMode.ProductAnalytics)

            await expectLogic(logic, () => {
                logic.actions.reconnectToStream()
            })

            expect(streamSpy).toHaveBeenCalledWith(
                expect.objectContaining({
                    conversation: MOCK_CONVERSATION_ID,
                    agent_mode: AgentMode.ProductAnalytics,
                }),
                expect.any(Object)
            )
        })
    })

    describe('scene to agent mode mapping', () => {
        it('does not auto-set mode when conversation already exists', async () => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
            logic.mount()

            // Set a conversation first
            logic.actions.setConversation(MOCK_CONVERSATION)

            // Set agent mode manually
            logic.actions.setAgentMode(AgentMode.SQL)

            // Simulate what would happen if scene changed - directly call sync
            // The logic should NOT change mode because conversation exists
            logic.actions.syncAgentModeFromConversation(AgentMode.ProductAnalytics)

            // Mode should update since syncAgentModeFromConversation doesn't check for conversation
            // (that check is in the subscription, not the action)
            await expectLogic(logic).toMatchValues({
                agentMode: AgentMode.ProductAnalytics,
            })
        })

        it('syncAgentModeFromConversation does not lock agent mode', async () => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, panelId: 'test' })
            logic.mount()

            // Sync should not lock
            logic.actions.syncAgentModeFromConversation(AgentMode.SQL)

            await expectLogic(logic).toMatchValues({
                agentMode: AgentMode.SQL,
                agentModeLockedByUser: false,
            })
        })
    })

    describe('sandbox streaming lock', () => {
        const sandboxRunResponse = {
            task_id: 'task-1',
            run_id: 'run-1',
            trace_id: 'trace-1',
            run_status: 'queued' as const,
            just_created_run: true,
        }

        beforeEach(() => {
            // jsdom has no EventSource — a minimal stub lets openSseForRun set up its connection
            ;(globalThis as any).EventSource = class {
                onopen: ((event: Event) => void) | null = null
                onmessage: ((event: MessageEvent<string>) => void) | null = null
                addEventListener(): void {}
                close(): void {}
            }
        })

        afterEach(() => {
            delete (globalThis as any).EventSource
        })

        it('holds the streaming lock until the sandbox turn completes and releases exactly once', async () => {
            const openSpy = jest.spyOn(api.conversations, 'open').mockResolvedValue(sandboxRunResponse)

            await expectLogic(logic, () => {
                logic.actions.streamConversation(
                    { agent_mode: null, is_sandbox: true, content: 'hello', conversation: MOCK_CONVERSATION_ID },
                    0
                )
            }).toDispatchActions(['openSandboxSse'])

            expect(openSpy).toHaveBeenCalledWith(
                MOCK_CONVERSATION_ID,
                expect.objectContaining({
                    content: 'hello',
                    initial_permission_mode: 'auto',
                })
            )

            // The POST finished, but the turn is still streaming — the lock must still be held
            expect(maxLogicInstance.values.activeStreamingThreads).toEqual(1)

            // The thread logic connects to the instance keyed by its own conversationId
            const sandboxStreamInstance = runStreamLogic({ streamKey: MOCK_CONVERSATION_ID })

            // The release listeners are synchronous, so the lock state settles with the dispatch
            sandboxStreamInstance.actions.markTurnComplete()
            expect(maxLogicInstance.values.activeStreamingThreads).toEqual(0)

            // A later terminal event must not release the (already released) lock again
            maxLogicInstance.actions.incrActiveStreamingThreads()
            sandboxStreamInstance.actions.handleTerminalStatus({ status: 'completed' })
            expect(maxLogicInstance.values.activeStreamingThreads).toEqual(1)
            maxLogicInstance.actions.decrActiveStreamingThreads()
        })

        it('does not release the lock on a non-terminal task_run_state frame', async () => {
            jest.spyOn(api.conversations, 'open').mockResolvedValue(sandboxRunResponse)

            await expectLogic(logic, () => {
                logic.actions.streamConversation(
                    { agent_mode: null, is_sandbox: true, content: 'hello', conversation: MOCK_CONVERSATION_ID },
                    0
                )
            }).toDispatchActions(['openSandboxSse'])

            const sandboxStreamInstance = runStreamLogic({ streamKey: MOCK_CONVERSATION_ID })

            // queued / in_progress frames arrive before the turn is done — the lock must stay held.
            sandboxStreamInstance.actions.handleTerminalStatus({ status: 'queued' })
            expect(maxLogicInstance.values.activeStreamingThreads).toEqual(1)
            sandboxStreamInstance.actions.handleTerminalStatus({ status: 'in_progress' })
            expect(maxLogicInstance.values.activeStreamingThreads).toEqual(1)

            // Only an actually-terminal status releases it.
            sandboxStreamInstance.actions.handleTerminalStatus({ status: 'completed' })
            expect(maxLogicInstance.values.activeStreamingThreads).toEqual(0)
        })

        it('lights the optimistic boot indicator before the open POST and clears it once the SSE opens', async () => {
            jest.spyOn(api.conversations, 'open').mockResolvedValue(sandboxRunResponse)

            await expectLogic(logic, () => {
                logic.actions.streamConversation(
                    { agent_mode: null, is_sandbox: true, content: 'hello', conversation: MOCK_CONVERSATION_ID },
                    0
                )
            }).toDispatchActions(['setSandboxRunOpening', 'openSandboxSse'])

            // openSandboxSse clears the optimistic flag via the reducer, so it never sticks on success.
            expect(runStreamLogic({ streamKey: MOCK_CONVERSATION_ID }).values.runOpening).toEqual(false)
        })

        it('releases the lock immediately and surfaces an error when the send POST fails', async () => {
            jest.spyOn(api.conversations, 'open').mockRejectedValue(new Error('boom'))

            await expectLogic(logic, () => {
                logic.actions.streamConversation(
                    { agent_mode: null, is_sandbox: true, content: 'hello', conversation: MOCK_CONVERSATION_ID },
                    0
                )
            }).toDispatchActions(['pushSandboxError', 'decrActiveStreamingThreads'])

            expect(maxLogicInstance.values.activeStreamingThreads).toEqual(0)
            // The boot indicator must not stick once the failed send unwinds.
            expect(runStreamLogic({ streamKey: MOCK_CONVERSATION_ID }).values.runOpening).toEqual(false)
            expect(
                runStreamLogic({ streamKey: MOCK_CONVERSATION_ID }).values.threadItems.some(
                    (item) =>
                        item.type === 'error' && item.errorMessage === 'Failed to send your message. Please try again.'
                )
            ).toEqual(true)
        })

        it('releases the lock immediately when no run was started', async () => {
            const openSpy = jest.spyOn(api.conversations, 'open')

            await expectLogic(logic, () => {
                logic.actions.streamConversation(
                    { agent_mode: null, is_sandbox: true, content: null, conversation: MOCK_CONVERSATION_ID },
                    0
                )
            }).toDispatchActions(['decrActiveStreamingThreads'])

            expect(openSpy).not.toHaveBeenCalled()
            expect(maxLogicInstance.values.activeStreamingThreads).toEqual(0)
        })
    })

    describe('sandbox streamingActive teardown', () => {
        const sandboxRunResponse = {
            task_id: 'task-1',
            run_id: 'run-1',
            trace_id: 'trace-1',
            run_status: 'queued' as const,
            just_created_run: true,
        }

        beforeEach(() => {
            ;(globalThis as any).EventSource = class {
                onopen: ((event: Event) => void) | null = null
                onmessage: ((event: MessageEvent<string>) => void) | null = null
                addEventListener(): void {}
                close(): void {}
            }
            jest.spyOn(api.conversations, 'open').mockResolvedValue(sandboxRunResponse)
        })

        afterEach(() => {
            delete (globalThis as any).EventSource
        })

        async function startSandboxTurn(): Promise<ReturnType<typeof runStreamLogic.build>> {
            await expectLogic(logic, () => {
                logic.actions.streamConversation(
                    { agent_mode: null, is_sandbox: true, content: 'hello', conversation: MOCK_CONVERSATION_ID },
                    0
                )
            }).toDispatchActions(['openSandboxSse'])
            expect(logic.values.streamingActive).toBe(true)
            return runStreamLogic({ streamKey: MOCK_CONVERSATION_ID })
        }

        it('tears down streamingActive on markTurnComplete', async () => {
            const sandboxStreamInstance = await startSandboxTurn()

            await expectLogic(logic, () => {
                sandboxStreamInstance.actions.markTurnComplete()
            }).toDispatchActions(['completeThreadGeneration'])

            expect(logic.values.streamingActive).toBe(false)
            expect(logic.values.threadLoading).toBe(false)
        })

        it('tears down streamingActive on handleTerminalStatus', async () => {
            const sandboxStreamInstance = await startSandboxTurn()

            await expectLogic(logic, () => {
                sandboxStreamInstance.actions.handleTerminalStatus({ status: 'completed' })
            }).toDispatchActions(['endStreaming'])

            expect(logic.values.streamingActive).toBe(false)
            expect(logic.values.threadLoading).toBe(false)
        })

        it('tears down streamingActive on handleStreamError', async () => {
            const sandboxStreamInstance = await startSandboxTurn()

            await expectLogic(logic, () => {
                sandboxStreamInstance.actions.handleStreamError({
                    errorTitle: 'Error',
                    errorMessage: 'boom',
                    retryable: false,
                })
            }).toDispatchActions(['endStreaming'])

            expect(logic.values.streamingActive).toBe(false)
            expect(logic.values.threadLoading).toBe(false)
        })

        it('markTurnComplete drains the sandbox queue combined, without an optimistic echo', async () => {
            // No POSTHOG_AI_QUEUE_MESSAGES_SYSTEM flag — sandbox queueing is flag-independent.
            jest.spyOn(api.conversations.queue, 'clear').mockResolvedValue({ messages: [], max_queue_messages: 2 })

            const sandboxStreamInstance = await startSandboxTurn()
            // completeThreadGeneration's queue-drain only runs with a non-null conversation.
            // The id matches the mounted conversationId, so the setConversation listener won't clear the queue.
            logic.actions.setConversation(MOCK_CONVERSATION)
            logic.actions.setIsSandboxMode(true)
            logic.actions.setQueuedMessages([
                { id: 'queue-1', content: 'First', created_at: new Date().toISOString() },
                { id: 'queue-2', content: 'Second', created_at: new Date().toISOString() },
            ])

            // markTurnComplete tears down streaming, then the drain clears the queue and re-sends the
            // combined text with addToThread:false (so it renders on the live echo, not optimistically).
            await expectLogic(logic, () => {
                sandboxStreamInstance.actions.markTurnComplete()
            }).toDispatchActions([
                'completeThreadGeneration',
                'clearQueuedMessages',
                (action: any) => action.payload?.prompt === 'First\n\nSecond' && action.payload?.addToThread === false,
            ])
        })

        it('handleStreamError does NOT drain the sandbox queue (no clearQueuedMessages, no askMax)', async () => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.POSTHOG_AI_QUEUE_MESSAGES_SYSTEM]: true,
            })

            const sandboxStreamInstance = await startSandboxTurn()
            logic.actions.setIsSandboxMode(true)
            const queueMessage = { id: 'queue-1', content: 'Next message', created_at: new Date().toISOString() }
            logic.actions.setQueuedMessages([queueMessage])

            await expectLogic(logic, () => {
                sandboxStreamInstance.actions.handleStreamError({
                    errorTitle: 'Error',
                    errorMessage: 'boom',
                    retryable: false,
                })
            })
                .toDispatchActions(['endStreaming'])
                .toNotHaveDispatchedActions(['completeThreadGeneration', 'clearQueuedMessages', 'askMax'])

            expect(logic.values.streamingActive).toBe(false)
            // The failed turn must not auto-start the queued message
            expect(logic.values.queuedMessages).toEqual([queueMessage])

            featureFlagLogic.unmount()
        })

        it('history-replay terminal events do not fire teardown while streamingActive is false', async () => {
            // No live turn: streamingActive is false (no streamConversation was dispatched)
            expect(logic.values.streamingActive).toBe(false)
            const sandboxStreamInstance = runStreamLogic({ streamKey: MOCK_CONVERSATION_ID })

            await expectLogic(logic, () => {
                sandboxStreamInstance.actions.handleTerminalStatus({ status: 'completed', replayedFromHistory: true })
            }).toNotHaveDispatchedActions(['endStreaming', 'completeThreadGeneration', 'askMax'])

            expect(logic.values.streamingActive).toBe(false)
        })
    })
})
