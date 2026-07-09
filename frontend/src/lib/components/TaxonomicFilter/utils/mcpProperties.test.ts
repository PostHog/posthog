import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    buildTaxonomicGroups,
    BuildTaxonomicGroupsContext,
} from 'lib/components/TaxonomicFilter/utils/buildTaxonomicGroups'
import {
    MCP_TOOL_CALL_EVENT,
    getMCPPropertyFilterOptions,
    includesMCPAnalyticsEvents,
} from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { getPrimaryPropertyForEvent } from 'lib/utils/events'

import { NodeKind } from '~/queries/schema/schema-general'
import { TeamType } from '~/types'

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

    describe('rebuild group availability (buildTaxonomicGroups)', () => {
        const baseContext: BuildTaxonomicGroupsContext = {
            currentTeam: { id: 997 } as TeamType,
            projectId: 997,
            groupAnalyticsTaxonomicGroups: [],
            groupAnalyticsTaxonomicGroupNames: [],
            eventNames: [],
            schemaColumns: [],
            schemaColumnsLoading: false,
            metadataSource: { kind: NodeKind.HogQLQuery, query: 'select event from events' },
            suggestedFiltersLabel: undefined,
            propertyFilters: { excludedProperties: {} },
            eventMetadataPropertyDefinitions: [],
            personMetadataPropertyDefinitions: [],
            maxContextOptions: [],
            hideBehavioralCohorts: false,
            endpointFilters: undefined,
            hogQLExpressionComponentProps: { showBreakdownLabelHint: false },
            featureFlags: {},
        }

        it('only offers the MCP properties group when scoped to canonical MCP events', () => {
            const unscoped = buildTaxonomicGroups(baseContext)
            expect(unscoped.find((g) => g.type === TaxonomicFilterGroupType.MCPProperties)).toBeUndefined()

            const scoped = buildTaxonomicGroups({ ...baseContext, eventNames: [MCP_TOOL_CALL_EVENT] })
            const mcpGroup = scoped.find((g) => g.type === TaxonomicFilterGroupType.MCPProperties)
            expect(mcpGroup).toBeTruthy()
            // Options remap to EventProperties so selecting one creates a plain event property filter.
            expect(mcpGroup?.options?.[0]).toEqual({
                name: '$mcp_tool_name',
                value: '$mcp_tool_name',
                group: TaxonomicFilterGroupType.EventProperties,
            })
        })

        it('seeds $mcp_is_error into SuggestedFilters when scoped to $mcp_tool_call', () => {
            const scoped = buildTaxonomicGroups({ ...baseContext, eventNames: [MCP_TOOL_CALL_EVENT] })
            const suggested = scoped.find((g) => g.type === TaxonomicFilterGroupType.SuggestedFilters)
            expect(suggested?.options).toContainEqual({
                name: '$mcp_is_error',
                group: TaxonomicFilterGroupType.EventProperties,
            })

            const unscoped = buildTaxonomicGroups(baseContext)
            const unscopedSuggested = unscoped.find((g) => g.type === TaxonomicFilterGroupType.SuggestedFilters)
            expect(unscopedSuggested?.options).not.toContainEqual({
                name: '$mcp_is_error',
                group: TaxonomicFilterGroupType.EventProperties,
            })
        })
    })
})
