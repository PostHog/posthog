import { useContext } from 'react'

import { ReferenceLine, useChartLayout } from '@posthog/quill-charts'

import { ResultChartSelectionContext } from './resultChartSelection'

export function ResultSelectionMarker(): JSX.Element | null {
    const { point } = useContext(ResultChartSelectionContext)
    const { series, labels, scales, dimensions, resolvePositionValue, theme } = useChartLayout()
    const selected = point && series.find((entry) => entry.key === point.seriesKey)
    const index = point ? labels.indexOf(point.label) : -1
    if (!selected || index < 0 || !Number.isFinite(selected.data[index]) || selected.visibility?.excluded) {
        return null
    }
    const x = scales.x(labels[index])
    const y = (scales.yAxes?.[selected.yAxisId ?? 'left']?.scale ?? scales.y)(resolvePositionValue(selected, index))
    if (
        x === undefined ||
        !Number.isFinite(x) ||
        !Number.isFinite(y) ||
        x < dimensions.plotLeft ||
        x > dimensions.plotLeft + dimensions.plotWidth ||
        y < dimensions.plotTop ||
        y > dimensions.plotTop + dimensions.plotHeight
    ) {
        return null
    }
    return (
        <>
            <ReferenceLine value={labels[index]} orientation="vertical" variant="marker" showValueOnHover={false} />
            <span
                data-attr="dashboard-result-selected-point"
                aria-label="Selected dashboard filter point"
                className="absolute pointer-events-none rounded-full border-2"
                style={{
                    left: x - 8,
                    top: y - 8,
                    width: 16,
                    height: 16,
                    borderColor: theme.backgroundColor,
                    backgroundColor: theme.backgroundColor,
                    boxShadow: `0 0 0 3px ${selected.color}`,
                }}
            >
                <span className="absolute inset-0.5 rounded-full" style={{ backgroundColor: selected.color }} />
            </span>
        </>
    )
}
