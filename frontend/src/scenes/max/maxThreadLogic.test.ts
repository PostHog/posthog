import { router } from 'kea-router'
import { partial } from 'kea-test-utils'
import { expectLogic } from 'kea-test-utils'
import React from 'react'

import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { NotebookTarget } from 'scenes/notebooks/types'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import * as notebooksModel from '~/models/notebooksModel'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'
import { ConversationDetail, ConversationStatus, ConversationType } from '~/types'

import { maxContextLogic } from './maxContextLogic'
import { maxGlobalLogic } from './maxGlobalLogic'
import { maxLogic } from './maxLogic'
import { maxThreadLogic } from './maxThreadLogic'
import {
    MOCK_CONVERSATION_ID,
    MOCK_IN_PROGRESS_CONVERSATION,
    MOCK_TEMP_CONVERSATION_ID,
    maxMocks,
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

    describe('invisible tool call filtering', () => {
        it('filters out invisible tool call messages from threadGrouped', async () => {
            await expectLogic(logic, () => {
                logic.actions.setThread([
                    {
                        type: AssistantMessageType.Human,
                        content: 'hello',
                        status: 'completed',
                        id: 'human-1',
                    },
                    {
                        type: AssistantMessageType.ToolCall,
                        content: 'invisible tool call',
                        status: 'completed',
                        id: 'tool-1',
                        visible: false,
                        tool_call_id: 'tool-1',
                        ui_payload: {},
                    },
                    {
                        type: AssistantMessageType.Assistant,
                        content: 'response',
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
                        {
                            type: AssistantMessageType.Assistant,
                            content: 'response',
                            status: 'completed',
                            id: 'assistant-1',
                        },
                    ],
                ],
            })
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
                    [
                        {
                            type: AssistantMessageType.Human,
                            content: 'test question',
                            status: 'completed',
                            id: 'human-1',
                        },
                    ],
                    [
                        {
                            type: AssistantMessageType.Failure,
                            content: 'Something went wrong',
                            status: 'completed',
                            id: 'failure-1',
                        },
                    ],
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

    describe('processNotebookUpdate', () => {
        it('navigates to notebook when not already on notebook page', async () => {
            router.actions.push(urls.max())

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
            const conversationWithoutMessages = {
                id: MOCK_CONVERSATION_ID,
                status: ConversationStatus.Idle,
                title: 'Empty conversation',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                messages: [],
                type: ConversationType.Assistant,
            }

            // Create logic with conversation containing no messages
            logic.unmount()
            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
                conversation: conversationWithoutMessages,
            })
            logic.mount()

            // Check that threadRaw is empty
            expect(logic.values.threadRaw).toEqual([])
        })

        it('updates threadRaw with status fields when conversation prop changes with new messages', async () => {
            // Start with empty conversation
            const initialConversation: ConversationDetail = {
                id: MOCK_CONVERSATION_ID,
                status: ConversationStatus.Idle,
                title: 'Test conversation',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                messages: [],
                type: ConversationType.Assistant,
            }

            logic.unmount()
            logic = maxThreadLogic({
                conversationId: MOCK_CONVERSATION_ID,
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

    describe('command selection and activation', () => {
        beforeEach(() => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID })
            logic.mount()
        })

        it('selectCommand sets question for command without arg', async () => {
            const initCommand = {
                name: '/init' as const,
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
                name: '/remember' as const,
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
                name: '/init' as const,
                description: 'Test command',
                icon: React.createElement('div'),
            }

            const askMaxSpy = jest.spyOn(logic.actions, 'askMax')

            logic.actions.activateCommand(initCommand)

            expect(askMaxSpy).toHaveBeenCalledWith('/init')
        })

        it('activateCommand sets question for command with arg', async () => {
            const rememberCommand = {
                name: '/remember' as const,
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
                name: '/remember' as const,
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
})
