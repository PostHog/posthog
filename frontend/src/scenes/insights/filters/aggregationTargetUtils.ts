export function getAggregationTargetPronoun(aggregation_group_type_index: number | null | undefined): 'who' | 'that' {
    return aggregation_group_type_index != null ? 'that' : 'who'
}
