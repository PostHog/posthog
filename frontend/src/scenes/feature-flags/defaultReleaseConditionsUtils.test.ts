import { FeatureFlagGroupType } from '~/types'

import { uniformAggregationGroupTypeIndex } from './defaultReleaseConditionsUtils'

describe('uniformAggregationGroupTypeIndex', () => {
    const group = (aggregation_group_type_index?: number | null): FeatureFlagGroupType => ({
        properties: [],
        rollout_percentage: 100,
        variant: null,
        aggregation_group_type_index,
    })

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
