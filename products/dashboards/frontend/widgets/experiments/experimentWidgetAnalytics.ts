import posthog from 'posthog-js'

/**
 * Fires when a user clicks "New experiment" from an experiment widget's empty state — i.e. they had
 * no experiments yet and started creating one from the widget. Pairs with the `experiment created`
 * event in the dashboard-widgets analytics funnel.
 */
export function captureCreateExperimentClicked(
    widgetType: 'experiments_list' | 'experiment_results',
    tileId: number
): void {
    posthog.capture('dashboard widget create experiment clicked', { widget_type: widgetType, tile_id: tileId })
}
