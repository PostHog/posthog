import { useActions, useValues } from 'kea'

import { LemonBanner, Link } from '@posthog/lemon-ui'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { traceDrawerLogic } from '../../redesign/trace/traceDrawerLogic'
import type { TraceListRow } from '../../redesign/trace/traceListRows'
import { evaluationSupportsReportHistory } from '../evaluationCapabilities'
import { EvaluationBackfillHint } from './EvaluationBackfillHint'
import { EvaluationDrawerEmptyState } from './EvaluationDrawerEmptyState'
import { EvaluationExamples } from './EvaluationExamples'
import { EvaluationLatestReportCard } from './EvaluationLatestReportCard'
import { describeAttention, hasIsolatedPoints } from './evaluationOverviewDisplay'
import { EvaluationPausedNotice } from './EvaluationPausedNotice'
import { EvaluationResultCards } from './EvaluationResultCards'
import { EvaluationResultDetails } from './EvaluationResultDetails'
import {
    EVALUATION_OVERVIEW_TRACES,
    type EvaluationExample,
    evaluationResultDrawerLogic,
} from './evaluationResultDrawerLogic'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationResultExpanded({ row }: { row: EvaluationResultApi }): JSX.Element {
    const { configById, timezone, evaluationUrl, buckets, interval } = useValues(evaluationsOverviewLogic)
    const { openDetails } = useValues(evaluationResultDrawerLogic)
    const { loadDetails } = useActions(evaluationResultDrawerLogic)
    const { setRows, openRow } = useActions(traceDrawerLogic({ listId: EVALUATION_OVERVIEW_TRACES }))
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

    const openExample = (example: EvaluationExample, examples: EvaluationExample[]): void => {
        const rows: TraceListRow[] = examples.flatMap(({ run }) =>
            run.traceId
                ? [
                      {
                          traceId: run.traceId,
                          timestamp: null,
                          stepId: run.targetEventId,
                          label: run.reasoning ?? undefined,
                      },
                  ]
                : []
        )
        const opened = rows.find((traceRow) => traceRow.traceId === example.run.traceId)
        if (opened) {
            setRows(rows)
            openRow(opened)
        }
    }

    return (
        <div className="@container flex flex-col gap-3">
            {notice}
            {evaluationSupportsReportHistory(config) && <EvaluationLatestReportCard evaluationId={row.id} />}
            <EvaluationResultCards
                row={row}
                buckets={buckets}
                interval={interval}
                timezone={timezone}
                details={openDetails}
                onRetryDetails={() => loadDetails(row.id, 'open')}
                chartFooter={hasIsolatedPoints(row) && <EvaluationBackfillHint row={row} source="drawer" />}
                showOutcomes={false}
                examples={
                    <EvaluationResultDetails load={openDetails} onRetry={() => loadDetails(row.id, 'open')}>
                        {(details) => (
                            <EvaluationExamples
                                examples={details.examples ?? []}
                                onOpen={(example) => openExample(example, details.examples ?? [])}
                            />
                        )}
                    </EvaluationResultDetails>
                }
            />
        </div>
    )
}
