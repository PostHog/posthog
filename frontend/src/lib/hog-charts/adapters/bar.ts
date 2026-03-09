import type { ChartConfiguration, ChartDataset } from 'chart.js'

import type { BarProps } from '../types'
import { mergeTheme } from '../utils/theme'
import { baseOptions, buildGoalLineAnnotations, buildScaleConfig, buildYAxes, resolveColor } from './common'

export function buildBarConfig(props: BarProps): ChartConfiguration<'bar'> {
    const theme = mergeTheme(props.theme)
    const horizontal = props.orientation === 'horizontal'
    const stacked = props.stacked ?? false
    const percentStacked = props.percentStacked ?? false

    const datasets: ChartDataset<'bar'>[] = props.data.map(
        (s, i) =>
            ({
                label: s.label,
                data: s.data,
                backgroundColor: resolveColor(s, i, theme),
                borderColor: resolveColor(s, i, theme),
                borderWidth: 0,
                borderRadius: props.borderRadius ?? 4,
                hidden: s.hidden,
                _hogMeta: s.meta,
            }) as ChartDataset<'bar'>
    )

    const yAxes = buildYAxes(props, theme, { startAtZero: true, gridLines: true })
    const opts = baseOptions(props, theme, props.data)

    const xScale = buildScaleConfig(props.xAxis, theme)
    if (stacked || percentStacked) {
        ;(xScale as Record<string, unknown>).stacked = true
        for (const key of Object.keys(yAxes)) {
            ;(yAxes as Record<string, Record<string, unknown>>)[key].stacked = true
        }
    }

    return {
        type: 'bar',
        data: { labels: props.labels, datasets },
        options: {
            ...opts,
            indexAxis: horizontal ? 'y' : 'x',
            scales: {
                x: xScale as never,
                ...yAxes,
            },
            plugins: {
                ...opts.plugins,
                annotation: {
                    annotations: buildGoalLineAnnotations(props.goalLines, theme),
                },
                stacked100: percentStacked ? { enable: true } : undefined,
                datalabels: props.showValues ? { display: true, color: theme.axisColor } : { display: false },
            },
        } as never,
    }
}
