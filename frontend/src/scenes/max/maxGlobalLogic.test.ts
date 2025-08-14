import { TOOL_DEFINITIONS, ToolRegistration } from './max-constants'
import { STATIC_TOOLS } from './maxGlobalLogic'

describe('maxGlobalLogic tool definitions', () => {
    it('all tool descriptions start with their name when provided', () => {
        const definitionsToCheck = (STATIC_TOOLS as Pick<ToolRegistration, 'name' | 'description'>[]).concat(
            Object.values(TOOL_DEFINITIONS)
        )
        for (const tool of definitionsToCheck) {
            if (tool.description) {
                expect(tool.description.startsWith(tool.name)).toBe(true)
            }
        }
    })
})
