import type { ChartConfiguration, ChartDataset } from 'chart.js'

import type { LifecycleProps } from '../types'
import { mergeTheme } from '../utils/theme'
import { baseOptions, buildGoalLineAnnotations, buildScaleConfig } from './common'

export function buildLifecycleConfig(props: LifecycleProps): ChartConfiguration<'bar'> {
    const theme = mergeTheme(props.theme)
    const defaultColors = {
        new: '#1AA35C',
        returning: '#1D4AFF',
        resurrecting: '#C73AC8',
        dormant: '#F04F58',
    }
    const colors = { ...defaultColors, ...props.statusColors }
    const visible = props.visibleStatuses ?? (['new', 'returning', 'resurrecting', 'dormant'] as const)

    const statuses = ['new', 'returning', 'resurrecting', 'dormant'] as const
    const datasets: ChartDataset<'bar'>[] = statuses
        .filter((s) => visible.includes(s))
        .map((status) => ({
            label: status.charAt(0).toUpperCase() + status.slice(1),
            data: props.data.map((bucket) => (status === 'dormant' ? -Math.abs(bucket[status]) : bucket[status])),
            backgroundColor: colors[status],
            borderWidth: 0,
            borderRadius: 2,
        }))

    const opts = baseOptions(props, theme)
    return {
        type: 'bar',
        data: { labels: props.labels, datasets },
        options: {
            ...opts,
            scales: {
                x: buildScaleConfig(props.xAxis, theme) as never,
                y: {
                    ...buildScaleConfig(props.yAxis, theme, { gridLines: true, startAtZero: true }),
                    stacked: true,
                } as never,
            },
            plugins: {
                ...opts.plugins,
                annotation: {
                    annotations: buildGoalLineAnnotations(props.goalLines, theme),
                },
            },
        } as never,
    }
}
