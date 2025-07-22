import {
    ConversionGoalFilter,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsHelperForColumnNames,
    MarketingAnalyticsTableQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import { injectDynamicConversionGoal, getOrderBy } from './utils'

describe('marketing analytics utils', () => {
    describe('injectDynamicConversionGoal', () => {
        it('should inject dynamic conversion goal after base columns and before conversion goal columns', () => {
            const selectList = [
                MarketingAnalyticsBaseColumns.Campaign.toString(),
                MarketingAnalyticsBaseColumns.Source.toString(),
                'existing_goal',
                'cost_per_existing_goal',
            ]
            const dynamicConversionGoal: ConversionGoalFilter = {
                conversion_goal_id: 'test-id',
                conversion_goal_name: 'test_goal',
                kind: NodeKind.EventsNode,
                event: 'test_event',
                name: 'Test Goal',
                math: BaseMathType.TotalCount,
                schema_map: {},
            }

            const result = injectDynamicConversionGoal(selectList, dynamicConversionGoal)

            expect(result).toContain('test_goal')
            expect(result).toContain(`${MarketingAnalyticsHelperForColumnNames.CostPer} test_goal`)

            // Check that the dynamic goal is inserted after base columns
            const sourceIndex = result.indexOf(MarketingAnalyticsBaseColumns.Source.toString())
            const testGoalIndex = result.indexOf('test_goal')
            const costPerTestGoalIndex = result.indexOf(`${MarketingAnalyticsHelperForColumnNames.CostPer} test_goal`)

            expect(testGoalIndex).toBeGreaterThan(sourceIndex)
            expect(costPerTestGoalIndex).toBeGreaterThan(sourceIndex)
            expect(costPerTestGoalIndex).toBe(testGoalIndex + 1)
        })

        it('should remove existing dynamic conversion goal from select list before injecting', () => {
            const selectList = [
                MarketingAnalyticsBaseColumns.Campaign.toString(),
                'test_goal', // Already exists
                'cost_per_test_goal', // Already exists
                'other_goal',
            ]
            const dynamicConversionGoal: ConversionGoalFilter = {
                conversion_goal_id: 'test-id',
                conversion_goal_name: 'test_goal',
                kind: NodeKind.EventsNode,
                event: 'test_event',
                name: 'Test Goal',
                math: BaseMathType.TotalCount,
                schema_map: {},
            }

            const result = injectDynamicConversionGoal(selectList, dynamicConversionGoal)

            // Should only have one instance of test_goal and cost_per_test_goal
            const testGoalCount = result.filter((col) => col === 'test_goal').length
            const costPerTestGoalCount = result.filter(
                (col) => col === `${MarketingAnalyticsHelperForColumnNames.CostPer} test_goal`
            ).length

            expect(testGoalCount).toBe(1)
            expect(costPerTestGoalCount).toBe(1)
        })

        it('should handle null dynamic conversion goal', () => {
            const selectList = [MarketingAnalyticsBaseColumns.Campaign.toString(), 'existing_goal']

            const result = injectDynamicConversionGoal(selectList, null)

            expect(result.length).toBe(selectList.length)
            expect(result.every((col) => selectList.includes(col))).toBe(true)
        })

        it('should handle empty select list', () => {
            const selectList: string[] = []
            const dynamicConversionGoal: ConversionGoalFilter = {
                conversion_goal_id: 'test-id',
                conversion_goal_name: 'test_goal',
                kind: NodeKind.EventsNode,
                event: 'test_event',
                name: 'Test Goal',
                math: BaseMathType.TotalCount,
                schema_map: {},
            }

            const result = injectDynamicConversionGoal(selectList, dynamicConversionGoal)

            expect(result.length).toBe(2)
            expect(result).toContain('test_goal')
            expect(result).toContain(`${MarketingAnalyticsHelperForColumnNames.CostPer} test_goal`)
        })

        it('should handle select list with only base columns', () => {
            const selectList = [
                MarketingAnalyticsBaseColumns.Campaign.toString(),
                MarketingAnalyticsBaseColumns.Source.toString(),
            ]
            const dynamicConversionGoal: ConversionGoalFilter = {
                conversion_goal_id: 'test-id',
                conversion_goal_name: 'test_goal',
                kind: NodeKind.EventsNode,
                event: 'test_event',
                name: 'Test Goal',
                math: BaseMathType.TotalCount,
                schema_map: {},
            }

            const result = injectDynamicConversionGoal(selectList, dynamicConversionGoal)

            expect(result.length).toBe(4)
            expect(result[0]).toBe(MarketingAnalyticsBaseColumns.Campaign.toString())
            expect(result[1]).toBe(MarketingAnalyticsBaseColumns.Source.toString())
            expect(result[2]).toBe('test_goal')
            expect(result[3]).toBe(`${MarketingAnalyticsHelperForColumnNames.CostPer} test_goal`)
        })
    })

    describe('getOrderBy', () => {
        it('should filter order by columns that exist in the columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
                orderBy: [
                    ['campaign', 'ASC'],
                    ['source', 'DESC'],
                    ['non_existent_column', 'ASC'],
                ],
            }
            const columns = ['campaign', 'source', 'other_column']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(2)
            expect(result.some((order) => order[0] === 'campaign' && order[1] === 'ASC')).toBe(true)
            expect(result.some((order) => order[0] === 'source' && order[1] === 'DESC')).toBe(true)
            expect(result.some((order) => order[0] === 'non_existent_column')).toBe(false)
        })

        it('should return empty array when query is undefined', () => {
            const columns = ['campaign', 'source']

            const result = getOrderBy(undefined, columns)

            expect(result.length).toBe(0)
        })

        it('should return empty array when query has no orderBy', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
            }
            const columns = ['campaign', 'source']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should return empty array when no order by columns exist in columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source'],
                orderBy: [
                    ['non_existent_column', 'ASC'],
                    ['another_non_existent', 'DESC'],
                ],
            }
            const columns = ['campaign', 'source']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should handle empty columns list', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign'],
                orderBy: [['campaign', 'ASC']],
            }
            const columns: string[] = []

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(0)
        })

        it('should preserve order of valid order by columns', () => {
            const query: MarketingAnalyticsTableQuery = {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                properties: [],
                select: ['campaign', 'source', 'medium'],
                orderBy: [
                    ['campaign', 'ASC'],
                    ['non_existent', 'DESC'],
                    ['source', 'DESC'],
                    ['medium', 'ASC'],
                ],
            }
            const columns = ['campaign', 'source', 'medium']

            const result = getOrderBy(query, columns)

            expect(result.length).toBe(3)
            expect(result[0][0]).toBe('campaign')
            expect(result[1][0]).toBe('source')
            expect(result[2][0]).toBe('medium')
        })
    })
})
