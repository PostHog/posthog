import { useValues } from 'kea'

import { Spinner } from '@posthog/quill'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { CheckCounts, ChecksSubject, passingChecks } from '../catalogTableRows'

type CatalogChecksSummaryProps = { row: ChecksSubject } | { counts: CheckCounts | null; subjectKey: string | undefined }

export function CatalogChecksSummary(props: CatalogChecksSummaryProps): JSX.Element | null {
    const { runningSubjectKey } = useValues(dataQualityOverviewLogic)
    const counts = 'row' in props ? passingChecks(props.row) : props.counts
    const subjectKey = 'row' in props ? props.row.checkGroup?.subjectKey : props.subjectKey
    if (subjectKey && runningSubjectKey === subjectKey) {
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
