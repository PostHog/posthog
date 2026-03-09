import type { ChartConfiguration } from 'chart.js'

import type { BoxPlotProps } from '../types'
import { mergeTheme } from '../utils/theme'
import { baseOptions, buildScaleConfig } from './common'

export function buildBoxPlotConfig(props: BoxPlotProps): ChartConfiguration {
    const theme = mergeTheme(props.theme)

    return {
        type: 'boxplot' as never,
        data: {
            labels: props.data.map((d) => d.label),
            datasets: [
                {
                    data: props.data.map((d) => ({
                        min: d.min,
                        q1: d.q1,
                        median: d.median,
                        q3: d.q3,
                        max: d.max,
                        mean: d.mean,
                        outliers: d.outliers ?? [],
                    })),
                    backgroundColor: `${theme.colors[0]}40`,
                    borderColor: theme.colors[0],
                    borderWidth: 2,
                    meanBackgroundColor: theme.colors[1],
                    meanBorderColor: theme.colors[1],
                    outlierBackgroundColor: `${theme.colors[2]}80`,
                } as never,
            ],
        },
        options: {
            ...baseOptions(props, theme),
            scales: {
                x: buildScaleConfig(props.xAxis, theme) as never,
                y: buildScaleConfig(props.yAxis, theme, { gridLines: true }) as never,
            },
        } as never,
    }
}
