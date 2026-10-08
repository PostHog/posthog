import clsx from 'clsx'

import { TimeSeriesComboChart, type PointClickData } from '@posthog/quill-charts'

import { AnnotationsLayer } from 'lib/components/AnnotationsOverlay/AnnotationsLayer'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { type SqlChartProps } from './SqlChart'
import { SqlChartTooltip } from './SqlChartTooltip'
import { SqlLineSeriesMeta, buildComboChartConfig } from './sqlLineGraphAdapter'
import { useSqlChartModel } from './useSqlChartModel'

const handleChartError = makeChartErrorHandler('sql-combo-chart')

/**
 * SQL mixed bar + line/area graph rendered via @posthog/quill-charts' {@link TimeSeriesComboChart}
 * (see {@link sqlChartComponentFor}). Handles the mixed-type case the line-only and bar-only paths
 * can't. Tooltip content (per-column formatting, total row) is configured in
 * {@link buildComboChartConfig}.
 */
export const SqlComboGraph = (props: SqlChartProps): JSX.Element => {
    const model = useSqlChartModel(props, buildComboChartConfig)

    return (
        <div
            className={clsx(
                props.className,
                'rounded bg-surface-primary w-full grow relative overflow-hidden flex flex-col',
                { 'h-[60vh]': props.presetChartHeight, 'h-full': !props.presetChartHeight }
            )}
        >
            {model && (
                <TimeSeriesComboChart<SqlLineSeriesMeta>
                    series={model.series}
                    labels={model.labels}
                    theme={model.theme}
                    config={model.config}
                    onError={handleChartError}
                    tooltip={
                        props.onPointClick
                            ? (context) => (
                                  <SqlChartTooltip
                                      context={context}
                                      config={model.config.tooltip}
                                      onPointClick={props.onPointClick!}
                                      hint={props.pointClickHint}
                                  />
                              )
                            : undefined
                    }
                    onPointClick={
                        props.onPointClick
                            ? (data: PointClickData<SqlLineSeriesMeta>) =>
                                  props.onPointClick?.(data.series.key, data.dataIndex, data.label)
                            : undefined
                    }
                >
                    {props.showAnnotations && props.insightNumericId && (
                        <AnnotationsLayer insightNumericId={props.insightNumericId} dates={model.labels} />
                    )}
                </TimeSeriesComboChart>
            )}
        </div>
    )
}
