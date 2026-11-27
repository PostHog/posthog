import { Sparkline } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

export interface TrendSparklineProps {
    series: number[]
}

// Hidden from assistive technology, because the occurrences and the change next to it carry the same facts as text.
export function TrendSparkline({ series }: TrendSparklineProps): JSX.Element {
    const theme = useChartTheme()
    return (
        <div className="w-24" aria-hidden>
            <Sparkline data={series} theme={theme} height={24} />
        </div>
    )
}
