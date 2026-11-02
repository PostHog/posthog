import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { MetricsWidgetChart } from 'products/metrics/frontend/widgets/MetricsWidgetChart'

import { WidgetCardBodyMessage, WidgetCardContent, WidgetLoadingState } from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { metricsWidgetNeedsConfiguration, metricsWidgetQuery } from './metricsWidgetConfig'

function isRunResult(result: unknown): boolean {
    return typeof result === 'object' && result !== null && !('needsConfiguration' in result)
}

export function MetricsWidget({ config, result, onEdit }: DashboardWidgetComponentProps): JSX.Element {
    // The config decides this state, so a tile saved a moment ago never shows the last run's result.
    if (metricsWidgetNeedsConfiguration(config)) {
        return (
            <WidgetCardBodyMessage>
                <div className="flex flex-col items-center gap-2">
                    <span>Choose a metric to chart on this tile.</span>
                    {onEdit ? (
                        <LemonButton type="primary" size="small" onClick={onEdit} data-attr="metrics-widget-configure">
                            Choose a metric
                        </LemonButton>
                    ) : null}
                </div>
            </WidgetCardBodyMessage>
        )
    }

    // A saved query waits here for its first run: a fetch error replaces the body, so no other state applies.
    if (!isRunResult(result)) {
        return <WidgetLoadingState />
    }

    return (
        <WidgetCardContent className="flex flex-col overflow-hidden p-2">
            <MetricsWidgetChart query={metricsWidgetQuery(config)} response={result} />
        </WidgetCardContent>
    )
}
