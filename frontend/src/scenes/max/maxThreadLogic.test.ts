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
import { AssistantEventType, AssistantMessage, AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { initKeaTests } from '~/test/init'
import { ConversationDetail, ConversationStatus, ConversationType } from '~/types'

import { EnhancedToolCall } from './Thread'
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

        logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, tabId: 'test' })
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
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, tabId: 'test' })
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
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, tabId: 'test' })
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
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, tabId: 'test' })
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
        logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, tabId: 'test' })
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

            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, tabId: 'test' })
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
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, tabId: 'test' })
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
                tabId: 'test',
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
                tabId: 'test',
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
                tabId: 'test',
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
                tabId: 'test',
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
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, tabId: 'test' })
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

    describe('assistant update event handling', () => {
        beforeEach(() => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, tabId: 'test' })
            logic.mount()
        })

        it('setToolCallUpdate adds update to toolCallUpdateMap', async () => {
            const updateEvent = {
                id: 'update-1',
                tool_call_id: 'tool-call-123',
                content: 'Processing data...',
            }

            await expectLogic(logic, () => {
                logic.actions.setToolCallUpdate(updateEvent)
            })

            expect(logic.values.toolCallUpdateMap.get('tool-call-123')).toEqual(['Processing data...'])
        })

        it('setToolCallUpdate adds multiple updates for same tool call', async () => {
            const toolCallId = 'tool-call-123'

            await expectLogic(logic, () => {
                logic.actions.setToolCallUpdate({
                    id: 'update-1',
                    tool_call_id: toolCallId,
                    content: 'Step 1 complete',
                })
                logic.actions.setToolCallUpdate({
                    id: 'update-2',
                    tool_call_id: toolCallId,
                    content: 'Step 2 complete',
                })
                logic.actions.setToolCallUpdate({
                    id: 'update-3',
                    tool_call_id: toolCallId,
                    content: 'Step 3 complete',
                })
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
                logic.actions.setToolCallUpdate({
                    id: 'update-1',
                    tool_call_id: toolCallId,
                    content: sameContent,
                })
                logic.actions.setToolCallUpdate({
                    id: 'update-2',
                    tool_call_id: toolCallId,
                    content: sameContent,
                })
            })

            // Should only have one entry despite two calls
            expect(logic.values.toolCallUpdateMap.get(toolCallId)).toEqual([sameContent])
        })

        it('setToolCallUpdate handles updates for different tool calls', async () => {
            await expectLogic(logic, () => {
                logic.actions.setToolCallUpdate({
                    id: 'update-1',
                    tool_call_id: 'tool-1',
                    content: 'Tool 1 update',
                })
                logic.actions.setToolCallUpdate({
                    id: 'update-2',
                    tool_call_id: 'tool-2',
                    content: 'Tool 2 update',
                })
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
                logic.actions.setToolCallUpdate({
                    id: 'update-1',
                    tool_call_id: 'tool-call-123',
                    content: 'This should not appear',
                })
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
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, tabId: 'test' })
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // Assistant responds with temp ID
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'Partial response',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // First streaming chunk
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'Partial',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // Second streaming chunk updates the same temp message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'Partial response updated',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // First assistant message starts
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'First message',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // Web search happens, new message starts
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-1',
                        type: AssistantMessageType.Assistant,
                        content: 'Second message after web search',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // Start with temp message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: 'temp-0',
                        type: AssistantMessageType.Assistant,
                        content: 'Streaming...',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // Finalize with real UUID
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: '550e8400-e29b-41d4-a716-446655440000',
                        type: AssistantMessageType.Assistant,
                        content: 'Complete response',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // Message without ID should be added as loading
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        type: AssistantMessageType.Assistant,
                        content: 'Streaming without ID',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // Add a message with final ID
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: finalId,
                        type: AssistantMessageType.Assistant,
                        content: 'First version',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )

                // Update the same message
                await onEventImplementation(
                    AssistantEventType.Message,
                    JSON.stringify({
                        id: finalId,
                        type: AssistantMessageType.Assistant,
                        content: 'Updated version',
                    }),
                    { actions: logic.actions, values: logic.values, props: logic.props }
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
                })
            })

            expect(logic.values.conversation).toEqual({
                ...newConversation,
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
                    { actions: logic.actions, values: logic.values, props: logic.props }
                )
            })

            expect(logic.values.threadRaw[logic.values.threadRaw.length - 1].status).toBe('error')
        })
    })

    describe('enhanceThreadToolCalls', () => {
        beforeEach(() => {
            logic = maxThreadLogic({ conversationId: MOCK_CONVERSATION_ID, tabId: 'test' })
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
            logic = maxThreadLogic({ conversationId: MOCK_TEMP_CONVERSATION_ID, tabId: 'test' })
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
                logic.actions.setToolCallUpdate({
                    id: 'update-1',
                    tool_call_id: toolCallId,
                    content: 'Progress update 1',
                })
                logic.actions.setToolCallUpdate({
                    id: 'update-2',
                    tool_call_id: toolCallId,
                    content: 'Progress update 2',
                })
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
    })
})
