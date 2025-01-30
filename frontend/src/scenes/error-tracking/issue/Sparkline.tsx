import { useValues } from 'kea'
import { Sparkline } from 'lib/components/Sparkline'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { errorTrackingLogic } from '../errorTrackingLogic'
import { sparklineLabels } from '../utils'

export type ErrorTrackingIssueEventsPanel = {
    key: 'stacktrace' | 'recording'
    Content: () => JSX.Element
    EmptyState: () => JSX.Element
    Header: string | (({ active }: { active: boolean }) => JSX.Element)
    hasContent: ({ hasStack, hasRecording }: { hasStack: boolean; hasRecording: boolean }) => boolean
    className?: string
}

export const SparklinePanel = (): JSX.Element | null => {
    const { customSparklineConfig } = useValues(errorTrackingLogic)
    const { issue } = useValues(errorTrackingIssueSceneLogic)

    if (!customSparklineConfig) {
        return null
    }

    const labels = sparklineLabels(customSparklineConfig)
    const data = issue?.aggregations?.customVolume || Array(labels.length).fill(0)

    return (
        <Sparkline loading={!issue?.aggregations?.customVolume} className="h-16 w-full" data={data} labels={labels} />
    )
}
