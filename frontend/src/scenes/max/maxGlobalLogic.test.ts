import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TOOL_DEFINITIONS, ToolDefinition } from './max-constants'
import { STATIC_TOOLS, maxGlobalLogic } from './maxGlobalLogic'
import { MOCK_CONVERSATION_ID, maxMocks } from './testUtils'

describe('maxGlobalLogic tool definitions', () => {
    it('all tool descriptions start with their name when provided', () => {
        const definitionsToCheck = (
            STATIC_TOOLS as (Pick<ToolDefinition, 'name' | 'description'> & {
                subtools?: Record<string, ToolDefinition>
            })[]
        ).concat(Object.values(TOOL_DEFINITIONS))
        for (const tool of definitionsToCheck) {
            if (tool.subtools) {
                for (const subtool of Object.values(tool.subtools)) {
                    if (subtool.description) {
                        expect(subtool.description.startsWith(subtool.name)).toBe(true)
                    }
                }
            } else if (tool.description) {
                expect(tool.description.startsWith(tool.name)).toBe(true)
            }
        }
    })
})

describe('maxGlobalLogic', () => {
    let logic: ReturnType<typeof maxGlobalLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        logic = maxGlobalLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    describe('editInsightToolRegistered selector', () => {
        it('returns true when contextual create_insight tool is registered', async () => {
            // Initially should be false (only static tool available)
            await expectLogic(logic).toMatchValues({
                editInsightToolRegistered: false,
            })

            logic.actions.registerTool({
                ...TOOL_DEFINITIONS.create_insight,
                identifier: 'create_insight',
            })

            // Now should be true (contextual tool is registered)
            await expectLogic(logic).toMatchValues({
                editInsightToolRegistered: true,
            })
        })
    })

    describe('loadConversation', () => {
        it('silently swallows 404 errors without dispatching a failure', async () => {
            useMocks({
                ...maxMocks,
                get: {
                    ...maxMocks.get,
                    [`/api/environments/:team_id/conversations/${MOCK_CONVERSATION_ID}`]: () => [
                        404,
                        { detail: 'Not found.' },
                    ],
                },
            })
            const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation()

            await expectLogic(logic, () => {
                logic.actions.loadConversation(MOCK_CONVERSATION_ID)
            })
                .toDispatchActions(['loadConversation', 'loadConversationSuccess'])
                .toNotHaveDispatchedActions(['loadConversationFailure'])
                .toMatchValues({
                    conversationHistory: [],
                })

            expect(captureSpy).not.toHaveBeenCalled()
        })

        it('lets non-404 errors surface as failures', async () => {
            useMocks({
                ...maxMocks,
                get: {
                    ...maxMocks.get,
                    [`/api/environments/:team_id/conversations/${MOCK_CONVERSATION_ID}`]: () => [
                        500,
                        { detail: 'Server error' },
                    ],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadConversation(MOCK_CONVERSATION_ID)
            }).toDispatchActions(['loadConversation', 'loadConversationFailure'])
        })
    })
})
