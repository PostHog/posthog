import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { dataQualityChecksLogic } from 'products/data_quality/frontend/dataQualityChecksLogic'

export function NodeDetailTestsTabLabel({ subjectId }: { subjectId: string }): JSX.Element {
    const { health } = useValues(dataQualityChecksLogic({ subjectType: 'view', subjectId }))
    const checksFailing = health?.checks_failing ?? 0

    return (
        <span className="flex items-center gap-1">
            Tests
            {checksFailing > 0 && <LemonTag type="danger">{checksFailing} failing</LemonTag>}
        </span>
    )
}
