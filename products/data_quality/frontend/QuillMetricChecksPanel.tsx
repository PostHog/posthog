import { useValues } from 'kea'

import { dataQualityChecksLogic } from './dataQualityChecksLogic'
import { QuillDataQualityChecksPanel } from './QuillDataQualityChecksPanel'
import { QuillDataQualitySchedule } from './QuillDataQualitySchedule'

export interface QuillMetricChecksPanelProps {
    metricId: string
    newCheckDisabledReason?: string
}

export function QuillMetricChecksPanel({
    metricId,
    newCheckDisabledReason,
}: QuillMetricChecksPanelProps): JSX.Element | null {
    const { checks } = useValues(dataQualityChecksLogic({ subjectType: 'metric', subjectId: metricId }))

    return (
        <QuillDataQualityChecksPanel
            subjectType="metric"
            subjectId={metricId}
            columns={[]}
            hideTitle
            newCheckDisabledReason={newCheckDisabledReason}
            notice={
                checks.length > 0 ? <QuillDataQualitySchedule subjectType="metric" subjectId={metricId} /> : undefined
            }
        />
    )
}
