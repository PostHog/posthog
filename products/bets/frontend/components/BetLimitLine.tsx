import { useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { timeToX } from '../lib/chartTime'

const LABEL_GLYPH_WIDTH = 6.2

export function BetLimitLine({
    value,
    label,
    avoid,
}: {
    value: number
    label: string
    avoid: string[]
}): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()
    const y = scales.y(value)
    const pinXs = useMemo(
        () =>
            avoid
                .map((at) => timeToX(at, labels, scales.x))
                .filter((x): x is number => x !== null)
                .sort((a, b) => b - a),
        [avoid, labels, scales.x]
    )
    if (!Number.isFinite(y) || y < dimensions.plotTop - 1 || y > dimensions.plotTop + dimensions.plotHeight + 1) {
        return null
    }
    const width = label.length * LABEL_GLYPH_WIDTH
    let right = dimensions.plotLeft + dimensions.plotWidth
    for (const x of pinXs) {
        if (x < right + 8 && x > right - width - 8) {
            right = x - 8
        }
    }
    return (
        <>
            <svg
                className="BetLimitLine absolute overflow-visible"
                style={{ left: dimensions.plotLeft, top: y, width: dimensions.plotWidth, height: 1 }}
                aria-hidden
            >
                <line x1={0} x2={dimensions.plotWidth} y1={0} y2={0} />
            </svg>
            {label && (
                <span
                    className="BetLimitLine__label absolute"
                    style={{ right: dimensions.width - right, bottom: dimensions.height - y + 5 }}
                >
                    {label}
                </span>
            )}
        </>
    )
}
