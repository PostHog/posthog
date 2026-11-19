import { useMemo } from 'react'

import { FunnelChart, ValueLabels } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { compactNumber } from 'lib/utils/numbers'

import type { Panel } from '../spec'
import { EmptyData } from './EmptyData'
import type { PanelCategory } from './panelData'

const percent = (value: number): string => `${parseFloat(value.toFixed(1))}%`

export function FunnelStepsChart({ panel, categories }: { panel: Panel; categories: PanelCategory[] }): JSX.Element {
    const theme = useChartTheme()
    const steps = useMemo(() => categories.map((category) => category.label), [categories])
    const first = categories[0]?.value ?? 0
    const series = useMemo(
        () => [
            {
                key: 'funnel',
                label: panel.title || 'Conversion',
                data: categories.map((category) => (first > 0 ? (category.value / first) * 100 : 0)),
            },
        ],
        [categories, first, panel.title]
    )

    if (!categories.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col">
            <FunnelChart
                className="min-h-0 flex-1"
                theme={theme}
                steps={steps}
                series={series}
                config={{ legend: { show: false }, stepFooterAlign: 'center' }}
                stepFooter={(index: number) => (
                    <div className="truncate px-1 pt-1 text-center text-xs leading-tight">
                        <div className="truncate font-medium" title={steps[index]}>
                            {steps[index]}
                        </div>
                        <div className="text-muted-foreground tabular-nums">
                            {compactNumber(categories[index]?.value ?? 0)}
                        </div>
                    </div>
                )}
            >
                <ValueLabels valueFormatter={percent} />
            </FunnelChart>
        </div>
    )
}
