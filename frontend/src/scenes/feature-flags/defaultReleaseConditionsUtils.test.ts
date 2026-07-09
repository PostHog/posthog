import { FeatureFlagGroupType } from '~/types'

import { distributeAggregationGroupTypeIndex, uniformAggregationGroupTypeIndex } from './defaultReleaseConditionsUtils'

const group = (aggregation_group_type_index?: number | null): FeatureFlagGroupType => ({
    properties: [],
    rollout_percentage: 100,
    variant: null,
    aggregation_group_type_index,
})

describe('uniformAggregationGroupTypeIndex', () => {
    it('returns null for no groups', () => {
        expect(uniformAggregationGroupTypeIndex([])).toBeNull()
    })

    it('returns null when no group is aggregated', () => {
        expect(uniformAggregationGroupTypeIndex([group(), group()])).toBeNull()
    })

    it('returns the shared index when every group agrees', () => {
        expect(uniformAggregationGroupTypeIndex([group(1), group(1)])).toBe(1)
    })

    it('preserves index 0 (first group type)', () => {
        expect(uniformAggregationGroupTypeIndex([group(0)])).toBe(0)
    })

    it('returns null for mixed indices', () => {
        expect(uniformAggregationGroupTypeIndex([group(1), group(2)])).toBeNull()
    })

    it('returns null when some groups are aggregated and others are not', () => {
        expect(uniformAggregationGroupTypeIndex([group(1), group()])).toBeNull()
    })
})

describe('distributeAggregationGroupTypeIndex', () => {
    it('returns the groups unchanged when the index is null', () => {
        const groups = [group(1), group()]
        expect(distributeAggregationGroupTypeIndex(groups, null)).toBe(groups)
    })

    it('does not stamp a null index onto groups that omit the field', () => {
        const groups = [group()]
        const result = distributeAggregationGroupTypeIndex(groups, null)
        expect('aggregation_group_type_index' in result[0] && result[0].aggregation_group_type_index).toBeFalsy()
    })

    it('stamps the index onto every group', () => {
        const result = distributeAggregationGroupTypeIndex([group(), group(2)], 1)
        expect(result.map((g) => g.aggregation_group_type_index)).toEqual([1, 1])
    })

    it('distributes index 0 (first group type)', () => {
        const result = distributeAggregationGroupTypeIndex([group(), group(1)], 0)
        expect(result.map((g) => g.aggregation_group_type_index)).toEqual([0, 0])
    })

    it('leaves already-matching groups referentially unchanged', () => {
        const matching = group(1)
        const result = distributeAggregationGroupTypeIndex([matching, group(2)], 1)
        expect(result[0]).toBe(matching)
        expect(result[1]).not.toBe(matching)
        expect(result[1].aggregation_group_type_index).toBe(1)
    })
})
