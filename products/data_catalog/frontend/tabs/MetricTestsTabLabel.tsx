import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'

export function MetricTestsTabLabel({ metricId }: { metricId: string }): JSX.Element {
    const { health } = useValues(dataQualityChecksLogic({ subjectType: 'metric', subjectId: metricId }))
    const failing = health?.checks_failing ?? 0

    return (
        <span className="flex items-center gap-1">
            Tests{failing > 0 && <LemonTag type="danger">{failing} failing</LemonTag>}
        </span>
    )
}
