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

    describe('tool registration instances', () => {
        it('keeps newer registrations when an older instance deregisters', async () => {
            logic.actions.registerTool({
                ...TOOL_DEFINITIONS.execute_sql,
                identifier: 'execute_sql' as const,
                registrationKey: 'sql-tab-one',
                context: { current_query: 'SELECT 1' },
            })
            logic.actions.registerTool({
                ...TOOL_DEFINITIONS.execute_sql,
                identifier: 'execute_sql' as const,
                registrationKey: 'sql-tab-two',
                context: { current_query: '' },
            })

            await expectLogic(logic).toMatchValues({
                toolMap: expect.objectContaining({
                    execute_sql: expect.objectContaining({
                        registrationKey: 'sql-tab-two',
                        context: { current_query: '' },
                    }),
                }),
            })

            logic.actions.deregisterTool('sql-tab-one')

            await expectLogic(logic).toMatchValues({
                toolMap: expect.objectContaining({
                    execute_sql: expect.objectContaining({
                        registrationKey: 'sql-tab-two',
                        context: { current_query: '' },
                    }),
                }),
            })
        })

        it('can still deregister legacy identifier-keyed tools', async () => {
            logic.actions.registerTool({
                ...TOOL_DEFINITIONS.execute_sql,
                identifier: 'execute_sql' as const,
            })

            logic.actions.deregisterTool('execute_sql')

            await expectLogic(logic).toMatchValues({
                registeredToolMap: {},
            })
        })
    })
})
