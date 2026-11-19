import { useMemo } from 'react'

import { SankeyChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { compactNumber } from 'lib/utils/numbers'

import { EmptyData } from './EmptyData'
import type { PanelFlow } from './panelData'

export function FlowsChart({ flows }: { flows: PanelFlow[] }): JSX.Element {
    const theme = useChartTheme()
    const nodes = useMemo(
        () => [...new Set(flows.flatMap((flow) => [flow.source, flow.target]))].map((id) => ({ id, label: id })),
        [flows]
    )

    if (!flows.length) {
        return <EmptyData />
    }
    return (
        <div className="relative flex h-full min-h-0 w-full flex-col">
            <SankeyChart
                className="min-h-0 flex-1"
                theme={theme}
                nodes={nodes}
                links={flows}
                config={{ valueFormatter: (value: number) => compactNumber(value), lastColumnLabels: 'outside' }}
            />
        </div>
    )
}
