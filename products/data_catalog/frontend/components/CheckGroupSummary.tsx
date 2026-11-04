import { useValues } from 'kea'

import { Spinner } from '@posthog/quill'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { CheckCounts } from '../catalogTableRows'

interface CheckGroupSummaryProps {
    counts: CheckCounts | null
    subjectKey: string | undefined
}

export function CheckGroupSummary({ counts, subjectKey }: CheckGroupSummaryProps): JSX.Element | null {
    const { runningSubjectKey } = useValues(dataQualityOverviewLogic)
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
