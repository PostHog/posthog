import './CountCell.scss'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { getDotMatrixCountBin } from './dotMatrixData'
import type { DotMatrixCountBin } from './types'

interface CountCellProps {
    value: number | null
    scale?: DotMatrixCountBin[]
    label?: string
    size?: 'xsmall' | 'small' | 'medium'
}

export function CountCell({ value, scale = [], label, size = 'medium' }: CountCellProps): JSX.Element {
    const width = size === 'xsmall' ? 36 : size === 'small' ? 38 : 44
    const height = size === 'xsmall' ? 22 : size === 'small' ? 24 : 28
    const count = value !== null && Number.isFinite(value) ? Math.max(0, value) : null
    const bin = count !== null ? getDotMatrixCountBin(count, scale) : undefined
    const text = count === null ? '' : count > 0 ? humanFriendlyLargeNumber(count) : '·'
    const valueLabel = count === null ? 'No value' : String(count)

    return (
        <svg
            className={`CountCell CountCell--${size}`}
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            role="img"
            aria-label={label ? `${label}: ${valueLabel}` : valueLabel}
        >
            <title>{valueLabel}</title>
            <rect
                width={width}
                height={height}
                rx={size === 'medium' ? 6 : 5}
                fill={count ? (bin?.color ?? 'var(--color-bg-fill-tertiary)') : 'transparent'}
            />
            <text
                x={width / 2}
                y={height / 2}
                textAnchor="middle"
                dominantBaseline="central"
                textLength={text.length > 4 ? width - 8 : undefined}
                lengthAdjust="spacingAndGlyphs"
                fill={count ? (bin?.ink ?? 'var(--color-text-primary)') : 'var(--color-text-tertiary)'}
            >
                {text}
            </text>
        </svg>
    )
}
