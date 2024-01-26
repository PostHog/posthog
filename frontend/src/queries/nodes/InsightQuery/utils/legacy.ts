export const isLegacyFunnelsFilter = (filters: Record<string, any> | undefined): boolean => {
    if (filters == null) {
        return false
    }

    const legacyKeys = [
        'funnel_viz_type',
        'funnel_from_step',
        'funnel_to_step',
        'funnel_step_reference',
        'breakdown_attribution_type',
        'breakdown_attribution_value',
        'bin_count',
        'funnel_window_interval_unit',
        'funnel_window_interval',
        'funnel_order_type',
        'hidden_legend_keys',
        'funnel_aggregate_by_hogql',
    ]
    return legacyKeys.some((key) => key in filters)
}

export const isLegacyRetentionFilter = (filters: Record<string, any> | undefined): boolean => {
    if (filters == null) {
        return false
    }

    const legacyKeys = ['retention_type', 'retention_reference', 'total_intervals', 'returning_entity', 'target_entity']
    return legacyKeys.some((key) => key in filters)
}
