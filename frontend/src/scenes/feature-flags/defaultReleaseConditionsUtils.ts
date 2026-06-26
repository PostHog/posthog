import { FeatureFlagGroupType } from '~/types'

// The shared group aggregation when every group agrees, otherwise null (mixed or none).
export function uniformAggregationGroupTypeIndex(groups: FeatureFlagGroupType[]): number | null {
    const indices = groups.map((group) => group.aggregation_group_type_index ?? null)
    return indices.length > 0 && indices.every((index) => index === indices[0]) ? indices[0] : null
}
