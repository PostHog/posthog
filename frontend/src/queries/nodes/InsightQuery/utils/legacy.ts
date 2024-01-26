export const isLegacyTrendsFilter = (filters: Record<string, any> | undefined): boolean => {
    if (filters == null) {
        return false
    }

    const legacyKeys = [
        'smoothing_intervals',
        'show_legend',
        'hidden_legend_keys',
        'aggregation_axis_format',
        'aggregation_axis_prefix',
        'aggregation_axis_postfix',
        'decimal_places',
        'show_values_on_series',
        'show_percent_stack_view',
        'show_labels_on_series',
    ]
    return legacyKeys.some((key) => key in filters)
}

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
