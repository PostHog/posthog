import { ExperimentMetric } from '~/queries/schema/schema-general'

import { useChartColors } from '../shared/colors'

interface ChartGradientsProps {
    lower?: number
    upper?: number
    gradientId?: string
    metric?: ExperimentMetric
}

/**
 * Shared gradient definitions for experiment charts.
 * This component should be included once in the parent SVG to avoid duplicate definitions.
 */
export function ChartGradients({
    lower = 0,
    upper = 0,
    gradientId = 'chart-gradient',
    metric,
}: ChartGradientsProps): JSX.Element {
    const colors = useChartColors()

    // Determine colors based on goal
    const getNegativeColor = (): string => {
        if (!metric?.goal) {
            return colors.BAR_NEGATIVE
        }
        return metric.goal === 'decrease' ? colors.BAR_POSITIVE : colors.BAR_NEGATIVE
    }

    const getPositiveColor = (): string => {
        if (!metric?.goal) {
            return colors.BAR_POSITIVE
        }
        return metric.goal === 'decrease' ? colors.BAR_NEGATIVE : colors.BAR_POSITIVE
    }

    const negativeColor = getNegativeColor()
    const positiveColor = getPositiveColor()

    if (lower < 0 && upper > 0) {
        const zeroOffset = (-lower / (upper - lower)) * 100
        return (
            <defs>
                <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
                    <stop offset="0%" stopColor={negativeColor} />
                    <stop offset={`${zeroOffset}%`} stopColor={negativeColor} />
                    <stop offset={`${zeroOffset}%`} stopColor={positiveColor} />
                    <stop offset="100%" stopColor={positiveColor} />
                </linearGradient>
            </defs>
        )
    }

    return (
        <defs>
            <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="0">
                <stop offset="100%" stopColor={upper <= 0 ? negativeColor : positiveColor} />
            </linearGradient>
        </defs>
    )
}
