import { Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { percentage } from 'lib/utils/numbers'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { formatCustomPropertyValue } from '../../scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import { buildHistoryDisplay, parseHistoryPoints } from './accountCustomPropertyDisplay'
import type { AccountColumnDisplayConfig } from './accountsColumnConfigLogic'

export function CustomPropertyHistoryCell({
    raw,
    definition,
    display,
}: {
    raw: unknown
    definition: CustomPropertyDefinitionApi
    display: AccountColumnDisplayConfig
}): JSX.Element {
    const { latest, baseline, chartPoints } = buildHistoryDisplay(
        parseHistoryPoints(raw),
        display.window_days,
        dayjs().valueOf()
    )

    if (!latest) {
        return <span className="text-muted">—</span>
    }
    const formatValue = (value: number): string => formatCustomPropertyValue(String(value), definition)
    if (chartPoints.length < 2) {
        return (
            <Tooltip title="Not enough history to chart yet. Showing the current value.">
                <span>{formatValue(latest[1])}</span>
            </Tooltip>
        )
    }

    if (display.mode === 'sparkline') {
        // Each sparkline auto-scales to its own range, so the line shows the trend but not the
        // magnitude — every row looks alike without the latest value spelled out next to it.
        return (
            // `min-w-min` lets the cell outgrow w-40 instead of spilling a long value into the next
            // column, and the chart keeps a floor so it degrades rather than vanishing.
            <div className="flex items-center gap-2 w-40 min-w-min">
                <span className="tabular-nums whitespace-nowrap">{formatValue(latest[1])}</span>
                <Sparkline
                    type="line"
                    className="h-8 min-w-8"
                    data={chartPoints.map(([, value]) => value)}
                    labels={chartPoints.map(([timestamp]) => dayjs.unix(timestamp).format('MMM D, YYYY HH:mm'))}
                    renderTooltipValue={formatValue}
                />
            </div>
        )
    }

    const delta = latest[1] - baseline![1]
    const deltaClass = delta > 0 ? 'text-success' : delta < 0 ? 'text-danger' : 'text-muted'
    // Percentage change against the window-start value; a zero baseline has no
    // meaningful ratio, so fall back to the absolute delta.
    const deltaText =
        delta === 0
            ? 'No change'
            : baseline![1] === 0
              ? `${delta > 0 ? '+' : '-'}${formatValue(Math.abs(delta))}`
              : `${delta > 0 ? '+' : '-'}${percentage(Math.abs(delta / baseline![1]), 1)}`
    return (
        <Tooltip
            title={`${formatValue(latest[1])} now, compared to ${formatValue(baseline![1])} ${display.window_days} days ago`}
        >
            <span className="inline-flex items-baseline gap-1.5">
                <span>{formatValue(latest[1])}</span>
                <span className={`text-xs ${deltaClass}`}>{deltaText}</span>
            </span>
        </Tooltip>
    )
}
