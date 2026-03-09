import type { ChartConfiguration } from 'chart.js'

import type { PieProps } from '../types'
import { mergeTheme, seriesColor } from '../utils/theme'
import { baseOptions } from './common'

export function buildPieConfig(props: PieProps): ChartConfiguration<'doughnut'> {
    const theme = mergeTheme(props.theme)
    const colors = props.data.map((d, i) => d.color ?? seriesColor(theme, i))

    const opts = baseOptions(props, theme)

    return {
        type: 'doughnut',
        data: {
            labels: props.data.map((d) => d.label),
            datasets: [
                {
                    data: props.data.map((d) => d.value),
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: theme.backgroundColor === 'transparent' ? '#fff' : theme.backgroundColor,
                },
            ],
        },
        options: {
            ...opts,
            cutout: (props.donut ?? true) ? `${(props.innerRadius ?? 0.6) * 100}%` : '0%',
            plugins: {
                ...opts.plugins,
                datalabels:
                    (props.showLabels ?? true)
                        ? {
                              display: true,
                              color: '#fff',
                              formatter: (_value: number, ctx: { dataIndex: number }) => {
                                  const total = props.data.reduce((sum, d) => sum + d.value, 0)
                                  const pct = ((props.data[ctx.dataIndex].value / total) * 100).toFixed(1)
                                  return `${pct}%`
                              },
                          }
                        : { display: false },
            },
        } as never,
    }
}
