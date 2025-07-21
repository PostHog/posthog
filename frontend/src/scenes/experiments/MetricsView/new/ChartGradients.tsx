import { useChartColors } from '../shared/colors'

interface ChartGradientsProps {
    lower?: number
    upper?: number
    gradientId?: string
}

/**
 * Shared gradient definitions for experiment charts.
 * This component should be included once in the parent SVG to avoid duplicate definitions.
 */
export function ChartGradients({
    lower = 0,
    upper = 0,
    gradientId = 'chart-gradient',
}: ChartGradientsProps): JSX.Element {
    const colors = useChartColors()

    if (lower < 0 && upper > 0) {
        const zeroOffset = (-lower / (upper - lower)) * 100
        return (
            <defs>
                <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
                    <stop offset="0%" stopColor={colors.BAR_NEGATIVE} />
                    <stop offset={`${zeroOffset}%`} stopColor={colors.BAR_NEGATIVE} />
                    <stop offset={`${zeroOffset}%`} stopColor={colors.BAR_POSITIVE} />
                    <stop offset="100%" stopColor={colors.BAR_POSITIVE} />
                </linearGradient>
            </defs>
        )
    }

    return (
        <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="0">
                <stop offset="100%" stopColor={upper <= 0 ? colors.BAR_NEGATIVE : colors.BAR_POSITIVE} />
            </linearGradient>
        </defs>
    )
}
