import type { ChartAssemblyInput } from 'flint-chart/core'
import { useMemo } from 'react'

import { BarChart, LineChart, PieChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { assembleQuill } from './assembleQuill'
import type { QuillChartSpec } from './types'

export interface FlintQuillChartProps {
    /** A Flint chart input: inline rows + semantic types + a compact chart spec. */
    input: ChartAssemblyInput
    className?: string
    dataAttr?: string
}

type AssemblyResult = { ok: true; spec: QuillChartSpec } | { ok: false; error: string }

/** Renders a Flint chart spec with quill-charts: compiles the input through
 *  Flint's semantic/layout pipeline via `assembleQuill()` and renders the
 *  resulting component with the app chart theme. */
export function FlintQuillChart({ input, className, dataAttr }: FlintQuillChartProps): JSX.Element {
    const theme = useChartTheme()
    const result = useMemo((): AssemblyResult => {
        try {
            return { ok: true, spec: assembleQuill(input) }
        } catch (e) {
            return { ok: false, error: e instanceof Error ? e.message : String(e) }
        }
    }, [input])

    if (!result.ok) {
        return <div className="text-danger text-sm p-2">Could not render chart: {result.error}</div>
    }

    const spec = result.spec
    switch (spec.component) {
        case 'BarChart':
            return (
                <BarChart
                    series={spec.series}
                    labels={spec.labels}
                    config={spec.config}
                    theme={theme}
                    className={className}
                    dataAttr={dataAttr}
                />
            )
        case 'LineChart':
            return (
                <LineChart
                    series={spec.series}
                    labels={spec.labels}
                    config={spec.config}
                    theme={theme}
                    className={className}
                    dataAttr={dataAttr}
                />
            )
        case 'PieChart':
            return (
                <PieChart
                    series={spec.series}
                    config={spec.config}
                    theme={theme}
                    className={className}
                    dataAttr={dataAttr}
                />
            )
    }
}
