import { useMemo } from 'react'

import { Sparkline } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

export interface KpiTileSparklineProps {
    series: (number | null)[]
}

export function KpiTileSparkline({ series }: KpiTileSparklineProps): JSX.Element {
    const theme = useChartTheme()
    const data = useMemo(() => series.map((value) => value ?? NaN), [series])
    return <Sparkline data={data} theme={theme} height={32} />
}
