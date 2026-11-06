import { useMemo } from 'react'

import { ProportionBar } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { pluralize } from 'lib/utils/strings'

import type { TopicCoverageApi } from '../generated/api.schemas'
import { TOPIC_COVERAGE_PARTS } from './topicCoverageParts'

function sessions(value: number): string {
    return pluralize(value, 'session')
}

export function TopicCoverageBar({
    coverage,
    maxAsked,
}: {
    coverage: TopicCoverageApi
    maxAsked: number
}): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () =>
            TOPIC_COVERAGE_PARTS.map(({ key, label, colorVar }) => ({
                key,
                label,
                data: [coverage[key]],
                color: getColorVar(colorVar),
            })),
        [coverage]
    )

    const asked = coverage.metric + coverage.table + coverage.nothing
    if (asked === 0) {
        return <span className="text-secondary text-xs">No session looked for a metric</span>
    }

    return (
        <div className="flex h-7 min-w-32 items-center gap-2">
            <div className="flex min-w-0 flex-1">
                <div
                    className="flex min-w-2 flex-col justify-center"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: `${(asked / maxAsked) * 100}%` }}
                >
                    <ProportionBar
                        series={series}
                        theme={theme}
                        valueFormatter={sessions}
                        config={{ barHeight: 12, barCornerRadius: 3, legend: { show: false } }}
                    />
                </div>
            </div>
            <span className="text-secondary w-6 shrink-0 text-right text-xs tabular-nums">{asked}</span>
        </div>
    )
}
