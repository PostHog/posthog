import { LemonModal } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'

import type { MetricsTableWidgetConfig } from '../../generated/widget-configs.zod'
import { buildMetricsTableDrilldownQueries } from './metricsTableDrilldown'

export function MetricsTableDrilldownModal({
    config,
    keys,
    onClose,
}: {
    config: MetricsTableWidgetConfig
    keys: string[]
    onClose: () => void
}): JSX.Element | null {
    if (keys.length === 0) {
        return null
    }
    const charts = buildMetricsTableDrilldownQueries(config, keys)
    return (
        <LemonModal
            isOpen
            onClose={onClose}
            width={1200}
            title={keys.length === 1 ? keys[0] : `${keys.length} ${config.groupBy} values`}
            description={keys.length === 1 ? undefined : keys.join(', ')}
        >
            <div className="flex flex-col gap-4" data-attr="metrics-table-widget-drilldown">
                {charts.map((chart, index) => (
                    <section key={index} className="flex flex-col gap-1">
                        <h5 className="m-0 text-sm font-semibold">{chart.title}</h5>
                        <div className="flex h-72 flex-col">
                            <Query query={chart.query} readOnly embedded />
                        </div>
                    </section>
                ))}
            </div>
        </LemonModal>
    )
}
