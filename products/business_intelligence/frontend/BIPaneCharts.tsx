import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonCard } from '@posthog/lemon-ui'

import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { SqlChart } from '~/queries/nodes/DataVisualization/Components/Charts/SqlChart'
import { Column } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { ChartSettings, GoalLine } from '~/queries/schema/schema-general'

import { buildBIPanes } from './biPanes'

export function BIPaneCharts({
    config,
    settings,
    columns,
    rows,
    goalLines,
    onInspect,
}: {
    config: BIConfig
    settings: ChartSettings
    columns: Column[]
    rows: unknown[][]
    goalLines: GoalLine[]
    onInspect?: (record: Record<string, unknown>) => void
}): JSX.Element {
    const { getTheme } = useValues(dataThemeLogic)
    const theme = useMemo(() => getTheme(undefined), [getTheme])
    const model = useMemo(
        () => buildBIPanes(config, settings, columns, rows, goalLines, theme),
        [config, settings, columns, rows, goalLines, theme]
    )
    const paneSettings = useMemo(
        () => ({ ...settings, showLegend: settings.showLegend ?? model.panes.some((pane) => pane.yData.length > 1) }),
        [settings, model]
    )
    if (model.error) {
        return <LemonBanner type="warning">{model.error}</LemonBanner>
    }
    return (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-2 overflow-y-auto p-2" data-attr="bi-pane-charts">
            {model.warnings.map((warning) => (
                <LemonBanner key={warning} type="info">
                    {warning}
                </LemonBanner>
            ))}
            <div
                className="grid gap-3"
                style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))' }}
            >
                {model.panes.map((pane) => (
                    <LemonCard key={pane.key} className="min-w-0 p-0" data-attr="bi-chart-pane">
                        <h3 className="m-0 break-words border-b px-3 py-2 text-sm">{pane.title}</h3>
                        <div className="h-80 min-w-0">
                            <SqlChart
                                className="p-2"
                                xData={pane.xData}
                                yData={pane.yData}
                                visualizationType={config.chartType}
                                chartSettings={paneSettings}
                                goalLines={pane.goalLines}
                                valueDomain={model.valueDomain}
                                labelFormatter={(label) => model.labels.get(label) ?? label}
                                xAxis={
                                    ['DATE', 'DATETIME'].includes(pane.xData.column.type.name)
                                        ? undefined
                                        : { tickFormatter: (label) => model.labels.get(label) ?? label }
                                }
                                embedded
                                directPointClick={!!onInspect}
                                pointClickHint={onInspect ? 'Click to explore this result' : undefined}
                                onPointClick={
                                    onInspect
                                        ? (seriesKey, index) => {
                                              const record = pane.records.get(JSON.stringify([seriesKey, index]))
                                              if (record) {
                                                  onInspect(record)
                                              }
                                          }
                                        : undefined
                                }
                            />
                        </div>
                    </LemonCard>
                ))}
            </div>
        </div>
    )
}
