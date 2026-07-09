import { FeatureFlagGroupType } from '~/types'

// The shared group aggregation when every group agrees, otherwise null (mixed or none).
export function uniformAggregationGroupTypeIndex(groups: FeatureFlagGroupType[]): number | null {
    const indices = groups.map((group) => group.aggregation_group_type_index ?? null)
    return indices.length > 0 && indices.every((index) => index === indices[0]) ? indices[0] : null
}

// Mirror a top-level group aggregation onto every group — the inverse of uniformAggregationGroupTypeIndex.
// A null index leaves each group's own index untouched (so mixed-targeting per-group values survive and
// loading a saved config doesn't dirty the form); groups already at the target index are returned as-is
// to keep the dirty-check stable.
export function distributeAggregationGroupTypeIndex(
    groups: FeatureFlagGroupType[],
    index: number | null
): FeatureFlagGroupType[] {
    if (index === null) {
        return groups
    }
    return groups.map((group) =>
        group.aggregation_group_type_index === index ? group : { ...group, aggregation_group_type_index: index }
    )
}
