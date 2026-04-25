import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TOOL_DEFINITIONS, ToolDefinition } from './max-constants'
import { STATIC_TOOLS, maxGlobalLogic } from './maxGlobalLogic'
import { maxMocks } from './testUtils'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
        info: jest.fn(),
        warning: jest.fn(),
    },
}))

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
})

describe('maxGlobalLogic auto-load conversation history', () => {
    let logic: ReturnType<typeof maxGlobalLogic.build>

    beforeEach(() => {
        ;(lemonToast.error as jest.Mock).mockClear()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('does not show a toast when the AI_FIRST auto-load fails', async () => {
        useMocks({
            ...maxMocks,
            get: {
                '/api/environments/:team_id/conversations/': () => [500, { detail: 'Internal Server Error' }],
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.AI_FIRST]: true })

        logic = maxGlobalLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadConversationHistory', 'loadConversationHistoryFailure'])

        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('shows a toast when a user-initiated load fails after the auto-load succeeded', async () => {
        let shouldFail = false
        useMocks({
            ...maxMocks,
            get: {
                '/api/environments/:team_id/conversations/': () =>
                    shouldFail ? [500, { detail: 'Boom' }] : [200, { results: [] }],
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.AI_FIRST]: true })

        logic = maxGlobalLogic()
        logic.mount()

        // Wait for the auto-load to settle so the silencing flag is cleared
        await expectLogic(logic).toDispatchActions(['loadConversationHistory', 'loadConversationHistorySuccess'])

        // Now simulate a user-initiated retry that fails
        shouldFail = true
        await expectLogic(logic, () => {
            logic.actions.loadConversationHistory()
        }).toDispatchActions(['loadConversationHistory', 'loadConversationHistoryFailure'])

        expect(lemonToast.error).toHaveBeenCalledTimes(1)
    })

    it('does not auto-load when the AI_FIRST flag is disabled', async () => {
        useMocks(maxMocks)
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], {})

        logic = maxGlobalLogic()
        logic.mount()
        await expectLogic(logic).delay(0).toNotHaveDispatchedActions(['loadConversationHistory'])
    })
})
