import { FlameGraph, type FlameNode } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { compactNumber } from 'lib/utils/numbers'

import { EmptyData } from './EmptyData'

export function FlameGraphChart({ roots, height }: { roots: FlameNode[]; height: number }): JSX.Element {
    const theme = useChartTheme()

    if (!roots.length) {
        return <EmptyData />
    }
    return (
        <div className="h-full min-h-0 w-full overflow-auto">
            <FlameGraph
                theme={theme}
                data={roots}
                config={{
                    valueFormatter: (value: number) => compactNumber(value),
                    maxHeight: Math.max(120, height - 8),
                }}
            />
        </div>
    )
}
