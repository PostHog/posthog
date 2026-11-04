import {
    MCP_TOOL_CALL_EVENT,
    getMCPPropertyFilterOptions,
    includesMCPAnalyticsEvents,
} from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { getPrimaryPropertyForEvent } from 'lib/utils/events'

describe('mcpProperties', () => {
    it('leads with the funnel-relevant properties and derives the rest of the known schema', () => {
        const options = getMCPPropertyFilterOptions()

        expect(options.slice(0, 4)).toEqual([
            '$mcp_tool_name',
            '$mcp_tool_category',
            '$mcp_is_error',
            '$mcp_error_type',
        ])
        // Non-priority schema properties come from the taxonomy-derived group, so new
        // $mcp_* taxonomy entries surface without touching this module.
        expect(options).toContain('$mcp_transport')
        expect(options).toContain('$mcp_llm_model')
        expect(options).toContain('$mcp_llm_model_source')
        expect(options.every((key) => key.startsWith('$mcp_'))).toBe(true)
        expect(new Set(options).size).toBe(options.length)
    })

    it.each([
        { eventNames: [MCP_TOOL_CALL_EVENT], expected: true },
        { eventNames: ['$mcp_tools_list'], expected: true },
        { eventNames: ['$pageview', MCP_TOOL_CALL_EVENT], expected: true },
        // Frozen legacy event names carry an unprefixed schema, so they don't count.
        { eventNames: ['mcp_tool_call'], expected: false },
        { eventNames: ['$pageview'], expected: false },
        { eventNames: [], expected: false },
    ])('includesMCPAnalyticsEvents($eventNames) is $expected', ({ eventNames, expected }) => {
        expect(includesMCPAnalyticsEvents(eventNames)).toBe(expected)
    })

    it('surfaces the tool name as the primary property of $mcp_tool_call', () => {
        // Guards the taxonomy entry and its regenerated JSON — this is what makes
        // tool-call funnel steps and event rows describe themselves by tool name.
        expect(getPrimaryPropertyForEvent(MCP_TOOL_CALL_EVENT)).toBe('$mcp_tool_name')
    })
})
