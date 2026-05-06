import { useMemo } from 'react'

import { buildYTickFormatter, type YFormatterConfig } from './y-formatters'

export interface XAxisConfig {
    tickFormatter?: (value: string, index: number) => string | null
    hide?: boolean
}

export interface YAxisConfig extends YFormatterConfig {
    scale?: 'linear' | 'log'
    /** Custom tick formatter. When set, it wins over `format`. */
    tickFormatter?: (value: number) => string
    hide?: boolean
    showGrid?: boolean
}

export function useYTickFormatter(yAxis: YAxisConfig | undefined): ((value: number) => string) | undefined {
    return useMemo(() => {
        if (yAxis?.tickFormatter) {
            return yAxis.tickFormatter
        }
        if (
            yAxis?.format === undefined &&
            yAxis?.prefix === undefined &&
            yAxis?.suffix === undefined &&
            yAxis?.decimalPlaces === undefined &&
            yAxis?.minDecimalPlaces === undefined &&
            yAxis?.currency === undefined
        ) {
            return undefined
        }
        return buildYTickFormatter({
            format: yAxis.format,
            prefix: yAxis.prefix,
            suffix: yAxis.suffix,
            decimalPlaces: yAxis.decimalPlaces,
            minDecimalPlaces: yAxis.minDecimalPlaces,
            currency: yAxis.currency,
        })
    }, [
        yAxis?.tickFormatter,
        yAxis?.format,
        yAxis?.prefix,
        yAxis?.suffix,
        yAxis?.decimalPlaces,
        yAxis?.minDecimalPlaces,
        yAxis?.currency,
    ])
}
