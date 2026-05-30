import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TOOL_DEFINITIONS, ToolDefinition } from './max-constants'
import { STATIC_TOOLS, maxGlobalLogic } from './maxGlobalLogic'
import { maxMocks } from './testUtils'

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

    describe('loadConversationHistory', () => {
        it('swallows a 404 (Max unavailable) without a toast or error', async () => {
            const toastSpy = jest.spyOn(lemonToast, 'error')
            useMocks({
                get: {
                    '/api/environments/:team_id/conversations/': () => [404, { detail: 'Endpoint not found.' }],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadConversationHistory()
            })
                .toDispatchActions(['loadConversationHistorySuccess'])
                .toNotHaveDispatchedActions(['loadConversationHistoryFailure'])
                .toMatchValues({ conversationHistory: [] })

            expect(toastSpy).not.toHaveBeenCalled()
        })

        it('still fails on non-404 errors', async () => {
            useMocks({
                get: {
                    '/api/environments/:team_id/conversations/': () => [500, { detail: 'Server error' }],
                },
            })

            await expectLogic(logic, () => {
                logic.actions.loadConversationHistory()
            }).toDispatchActions(['loadConversationHistoryFailure'])
        })
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
})
