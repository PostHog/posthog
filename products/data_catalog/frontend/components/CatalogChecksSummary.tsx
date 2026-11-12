import { useValues } from 'kea'

import { IconCheckCircle, IconWarning, IconXCircle } from '@posthog/icons'
import { Badge, Spinner } from '@posthog/quill'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { CheckCounts, ChecksSubject, passingChecks } from '../catalogTableRows'

type CatalogChecksSummaryProps = { row: ChecksSubject } | { counts: CheckCounts | null; subjectKey: string | undefined }

type ChecksOutcome = 'all_passing' | 'some_failing' | 'all_failing'

const OUTCOME_BADGES: Record<
    ChecksOutcome,
    { variant: 'success' | 'warning' | 'destructive'; Icon: typeof IconCheckCircle }
> = {
    all_passing: { variant: 'success', Icon: IconCheckCircle },
    some_failing: { variant: 'warning', Icon: IconWarning },
    all_failing: { variant: 'destructive', Icon: IconXCircle },
}

function checksOutcome({ total, failing }: CheckCounts): ChecksOutcome {
    if (failing === 0) {
        return 'all_passing'
    }
    return failing === total ? 'all_failing' : 'some_failing'
}

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
    const { variant, Icon } = OUTCOME_BADGES[checksOutcome(counts)]
    return (
        <Badge variant={variant} className="whitespace-nowrap tabular-nums">
            <Icon aria-hidden />
            <span>{`${counts.total - counts.failing}/${counts.total} passing`}</span>
        </Badge>
    )
}
