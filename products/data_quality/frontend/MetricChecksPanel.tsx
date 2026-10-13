import { useValues } from 'kea'

import { dataQualityChecksLogic } from './dataQualityChecksLogic'
import { DataQualityChecksPanel } from './DataQualityChecksPanel'
import { DataQualitySchedule } from './DataQualitySchedule'

interface MetricChecksPanelProps {
    metricId: string
    newCheckDisabledReason?: string
}

export function MetricChecksPanel({ metricId, newCheckDisabledReason }: MetricChecksPanelProps): JSX.Element | null {
    const { checks } = useValues(dataQualityChecksLogic({ subjectType: 'metric', subjectId: metricId }))

    return (
        <DataQualityChecksPanel
            subjectType="metric"
            subjectId={metricId}
            columns={[]}
            hideTitle
            newCheckDisabledReason={newCheckDisabledReason}
            notice={checks.length > 0 ? <DataQualitySchedule subjectType="metric" subjectId={metricId} /> : undefined}
        />
    )
}
