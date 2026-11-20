import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { evaluationSupportsReportHistory } from '../evaluationCapabilities'
import { EvaluationBackfillHint } from './EvaluationBackfillHint'
import { EvaluationDrawerEmptyState } from './EvaluationDrawerEmptyState'
import { EvaluationLatestReportCard } from './EvaluationLatestReportCard'
import { describeAttention, hasIsolatedPoints } from './evaluationOverviewDisplay'
import { EvaluationPausedNotice } from './EvaluationPausedNotice'
import { EvaluationResultCards } from './EvaluationResultCards'
import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationResultExpanded({ row }: { row: EvaluationResultApi }): JSX.Element {
    const { configById, timezone, evaluationUrl, buckets, interval } = useValues(evaluationsOverviewLogic)
    const { openDetails } = useValues(evaluationResultDrawerLogic)
    const { loadDetails } = useActions(evaluationResultDrawerLogic)
    const errored = row.attentionReasons.includes('errored')
    const config = configById.get(row.id)
    const enabled = config?.enabled ?? row.enabled

    const notice = errored ? (
        <LemonBanner type="error">
            <span>{`${describeAttention(row, timezone)}. `}</span>
            <Link to={evaluationUrl(row.id)}>Open the evaluation to fix it.</Link>
        </LemonBanner>
    ) : !enabled ? (
        <EvaluationPausedNotice row={row} />
    ) : null

    if (row.gradedCount === 0) {
        return <EvaluationDrawerEmptyState row={row} />
    }

    return (
        <div className="@container flex flex-col gap-3">
            {notice}
            {evaluationSupportsReportHistory(config) && (
                <EvaluationLatestReportCard
                    evaluationId={row.id}
                    reportUrl={(params) => evaluationUrl(row.id, params)}
                />
            )}
            <EvaluationResultCards
                row={row}
                buckets={buckets}
                interval={interval}
                timezone={timezone}
                details={openDetails}
                onRetryDetails={() => loadDetails(row.id, 'open')}
                chartFooter={hasIsolatedPoints(row) && <EvaluationBackfillHint row={row} source="drawer" />}
            />
        </div>
    )
}
