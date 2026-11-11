import { useValues } from 'kea'

import { Badge } from '@posthog/quill'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'

export function QuillMetricTestsTabLabel({ metricId }: { metricId: string }): JSX.Element {
    const { health } = useValues(dataQualityChecksLogic({ subjectType: 'metric', subjectId: metricId }))
    const failing = health?.checks_failing ?? 0

    return (
        <span className="flex items-center gap-1">
            <span>Data quality</span>
            {failing > 0 && <Badge variant="destructive">{`${failing} failing`}</Badge>}
        </span>
    )
}
