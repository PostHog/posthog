import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { traceDrawerLogic } from '../../redesign/trace/traceDrawerLogic'
import { EvaluationDetailDrawer } from '../components/EvaluationDetailDrawer'
import { EvaluationReportDrawer } from '../components/EvaluationReportDrawer'
import { evaluationReportDrawerLogic } from '../evaluationReportDrawerLogic'
import { llmEvaluationsLogic } from '../llmEvaluationsLogic'
import { EvaluationFixSuggestionNotice } from '../suggestions/EvaluationFixSuggestionNotice'
import { EVALUATION_OVERVIEW_TRACES, evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { EvaluationResultExpanded } from './EvaluationResultExpanded'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** One evaluation's results in a side panel, so the page keeps its place. Its report and traces open on top. */
export function EvaluationResultDrawer(): JSX.Element | null {
    const { openRow } = useValues(evaluationResultDrawerLogic)
    const { closeDrawer } = useActions(evaluationResultDrawerLogic)
    const { evaluationUrl, configById } = useValues(evaluationsOverviewLogic)
    const { setDates } = useActions(llmEvaluationsLogic)
    const { openRow: openTrace } = useActions(traceDrawerLogic({ listId: EVALUATION_OVERVIEW_TRACES }))
    const suggestionsEnabled = useFeatureFlag('LLM_ANALYTICS_EVAL_SUGGESTIONS')

    if (!openRow) {
        return null
    }
    const description = configById.get(openRow.id)?.description

    return (
        <>
            <EvaluationDetailDrawer
                title={openRow.name}
                onClose={closeDrawer}
                aria-label="Evaluation results"
                data-attr="evaluation-overview-drawer"
                actions={
                    <LemonButton
                        type="secondary"
                        size="small"
                        sideIcon={<IconArrowRight />}
                        to={evaluationUrl(openRow.id)}
                        data-attr="evaluation-overview-drawer-open"
                    >
                        Open evaluation
                    </LemonButton>
                }
            >
                <div className="flex flex-col gap-3">
                    {description && <p className="m-0 whitespace-pre-wrap text-sm text-secondary">{description}</p>}
                    {suggestionsEnabled && <EvaluationFixSuggestionNotice evaluationId={openRow.id} />}
                    <EvaluationResultExpanded row={openRow} />
                </div>
            </EvaluationDetailDrawer>
            <EvaluationReportDrawer
                evaluationId={openRow.id}
                onOpenTrace={(traceId, eventId) => openTrace({ traceId, timestamp: null, stepId: eventId })}
                onShowResults={(periodStart, periodEnd) => {
                    evaluationReportDrawerLogic({ evaluationId: openRow.id }).actions.close()
                    setDates(periodStart, periodEnd)
                }}
            />
        </>
    )
}
