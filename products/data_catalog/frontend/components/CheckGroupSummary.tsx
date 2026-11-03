import { useValues } from 'kea'

import { Spinner, Text } from '@posthog/quill'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { CheckCounts } from '../catalogTableRows'
import { MutedCellText } from '../tables/MutedCellText'

interface CheckGroupSummaryProps {
    counts: CheckCounts | null
    subjectKey: string | undefined
}

export function CheckGroupSummary({ counts, subjectKey }: CheckGroupSummaryProps): JSX.Element {
    const { runningSubjectKey } = useValues(dataQualityOverviewLogic)
    if (subjectKey && runningSubjectKey === subjectKey) {
        return (
            <Text size="xs" variant="muted" className="flex items-center gap-1 whitespace-nowrap">
                <Spinner />
                Running
            </Text>
        )
    }
    if (!counts) {
        return <MutedCellText>No checks</MutedCellText>
    }
    return (
        <span className="whitespace-nowrap tabular-nums">{`${counts.total - counts.failing}/${counts.total} passing`}</span>
    )
}
