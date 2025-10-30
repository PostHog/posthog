import { expectLogic } from 'kea-test-utils'

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

    describe('editInsightToolRegistered selector', () => {
        it('returns true when contextual create_and_query_insight tool is registered', async () => {
            // Initially should be false (only static tool available)
            await expectLogic(logic).toMatchValues({
                editInsightToolRegistered: false,
            })

            logic.actions.registerTool({
                ...TOOL_DEFINITIONS.create_and_query_insight,
                identifier: 'create_and_query_insight',
            })

            // Now should be true (contextual tool is registered)
            await expectLogic(logic).toMatchValues({
                editInsightToolRegistered: true,
            })
        })
    })
})
