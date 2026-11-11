import { useValues } from 'kea'

import { Spinner } from '@posthog/quill'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { ChecksSubject, passingChecks } from '../catalogTableRows'

export function CatalogChecksSummary({ row }: { row: ChecksSubject }): JSX.Element | null {
    const { runningSubjectKey } = useValues(dataQualityOverviewLogic)
    const counts = passingChecks(row)
    if (row.checkGroup && runningSubjectKey === row.checkGroup.subjectKey) {
        return (
            <span className="flex items-center gap-1 whitespace-nowrap">
                <Spinner />
                Running
            </span>
        )
    }
    if (!counts) {
        return null
    }
    return (
        <span className="whitespace-nowrap tabular-nums">{`${counts.total - counts.failing}/${counts.total} passing`}</span>
    )
}
