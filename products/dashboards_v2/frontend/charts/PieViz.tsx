import { PieChart } from '@posthog/quill-charts'

import { useDisplayChartTheme } from '../editor/display'
import { withOverrides } from './chartCommon'
import { colorize } from './colors'
import { EmptyData } from './EmptyData'
import { formatValue } from './format'
import { toCategories } from './frames'
import type { PieOptions as O } from './options'
import type { VizProps } from './registry'

export function PieViz({ frames, panel, options, onDrill }: VizProps<O>): React.JSX.Element {
    const theme = useDisplayChartTheme()
    const { labels, series, unit } = toCategories(frames)
    const firsts = series.filter((s) => !s.key.includes(':') || s.key.endsWith(':0'))
    const values = labels.map((_, i) => firsts.reduce((a, s) => a + (s.data[i] ?? 0), 0))
    if (!labels.length) {
        return <EmptyData />
    }
    return (
        <PieChart
            className="min-h-0 flex-1"
            theme={theme}
            series={colorize(
                panel,
                withOverrides(
                    panel,
                    labels.map((l, i) => ({ key: String(i), label: l, data: [values[i] ?? 0] }))
                ),
                theme.colors
            )}
            valueFormatter={(v) => formatValue(v, panel.fieldConfig?.unit ?? unit, panel.fieldConfig?.decimals)}
            onSliceClick={
                onDrill
                    ? (d) =>
                          onDrill({
                              refId: frames[0]?.refId,
                              category: labels[d.sliceIndex],
                              value: d.value,
                              row: {
                                  [frames
                                      .find((f) => f.fields.some((x) => x.type === 'string'))
                                      ?.fields.find((x) => x.type === 'string')?.name ?? 'category']:
                                      labels[d.sliceIndex],
                                  value: d.value,
                              },
                          })
                    : undefined
            }
            config={{
                innerRadiusRatio: options.donut ? 0.6 : 0,
                showLabelOnSlice: false,
                showValueOnSlice: options.showPercent,
                isPercent: options.showPercent,
                legend: {
                    show: options.legend !== 'none',
                    position: options.legend === 'none' ? 'right' : options.legend,
                },
            }}
        />
    )
}
