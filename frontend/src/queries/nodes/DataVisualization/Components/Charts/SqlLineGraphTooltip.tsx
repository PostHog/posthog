// TODO: Move the below scss to somewhere more common
import '../../../../../scenes/insights/InsightTooltip/InsightTooltip.scss'

import { IconX } from '@posthog/icons'
import { LemonTable } from '@posthog/lemon-ui'
import { type TooltipContext } from '@posthog/quill-charts'

import { InsightLabel } from 'lib/components/InsightLabel'

import { ChartSettings } from '~/queries/schema/schema-general'

import { SqlLineSeriesMeta, SqlLineTooltipRow, buildSqlLineTooltipModel } from './sqlLineGraphAdapter'

interface SqlLineGraphTooltipProps {
    context: TooltipContext<SqlLineSeriesMeta>
    chartSettings: ChartSettings
}

/**
 * The rich SQL line/area tooltip — a port of the legacy chart.js `InsightTooltip` (header + close,
 * a `LemonTable` of color-dotted series rows sorted by value, and a total row), driven by quill's
 * hover {@link TooltipContext} via the chart's `tooltip` render prop. Data shaping lives in
 * {@link buildSqlLineTooltipModel}; this component is purely presentational.
 */
export function SqlLineGraphTooltip({ context, chartSettings }: SqlLineGraphTooltipProps): JSX.Element {
    const { label, rows, totalLabel } = buildSqlLineTooltipModel(context, chartSettings)

    return (
        <div className="InsightTooltip">
            <div className="flex items-center justify-between pl-5 pr-2 py-2 text-xs font-semibold border-b border-primary">
                <span>{label}</span>
                {context.isPinned && context.onUnpin && (
                    <button
                        type="button"
                        className="InsightTooltip__close ml-5 p-0.5 rounded hover:bg-fill-button-tertiary-hover cursor-pointer"
                        onClick={context.onUnpin}
                    >
                        <IconX className="w-3 h-3" />
                    </button>
                )}
            </div>
            <div className="max-h-64 overflow-y-auto">
                <LemonTable
                    showHeader={false}
                    dataSource={rows}
                    columns={[
                        {
                            dataIndex: 'name',
                            render: (value) => (
                                <div className="datum-label-column">
                                    <InsightLabel
                                        fallbackName={value?.toString()}
                                        hideBreakdown
                                        showSingleName
                                        hideCompare
                                        hideIcon
                                        allowWrap
                                    />
                                </div>
                            ),
                        },
                        {
                            dataIndex: 'value',
                            render: (value) => <div className="series-data-cell text-right">{String(value)}</div>,
                        },
                    ]}
                    uppercaseHeader={false}
                    rowRibbonColor={(row: SqlLineTooltipRow) => row.color}
                />
            </div>
            {totalLabel && (
                <div className="flex justify-between px-5 py-2 text-xs font-bold border-t border-primary">
                    <span className="flex-1">Total</span>
                    <span className="text-right">{totalLabel}</span>
                </div>
            )}
        </div>
    )
}
