import type { ChartConfiguration, ChartDataset } from 'chart.js'

import { mergeTheme } from '../theme'
import type { BarProps } from '../types'

import { baseOptions, buildGoalLineAnnotations, buildScaleConfig, buildYAxes, resolveColor } from './common'

export function buildBarConfig(props: BarProps): ChartConfiguration<'bar'> {
    const theme = mergeTheme(props.theme)
    const horizontal = props.orientation === 'horizontal'

    const datasets: ChartDataset<'bar'>[] = props.data.map((s, i) => ({
        label: s.label,
        data: s.data,
        backgroundColor: resolveColor(s, i, theme),
        borderColor: resolveColor(s, i, theme),
        borderWidth: 0,
        borderRadius: props.borderRadius ?? 4,
        hidden: s.hidden,
        _hogMeta: s.meta,
    } as ChartDataset<'bar'>))

    const yAxes = buildYAxes(props, theme, { startAtZero: true, gridLines: true })
    const opts = baseOptions(props, theme, props.data)

    return {
        type: 'bar',
        data: { labels: props.labels, datasets },
        options: {
            ...opts,
            indexAxis: horizontal ? 'y' : 'x',
            scales: {
                x: buildScaleConfig(props.xAxis, theme) as never,
                ...yAxes,
            },
            plugins: {
                ...(opts.plugins as Record<string, unknown>),
                annotation: {
                    annotations: buildGoalLineAnnotations(props.goalLines, theme),
                },
                stacked100: props.percentStacked ? { enable: true } : undefined,
                datalabels: props.showValues ? { display: true, color: theme.axisColor } : { display: false },
            },
        } as never,
    }
}
