import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonDrawer } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { EvaluationResultExpanded } from './EvaluationResultExpanded'

/** One evaluation's results in a drawer, so the table keeps its place. */
export function EvaluationResultDrawer(): JSX.Element {
    const { openRow } = useValues(evaluationResultDrawerLogic)
    const { closeDrawer } = useActions(evaluationResultDrawerLogic)

    return (
        <LemonDrawer
            isOpen={!!openRow}
            onClose={closeDrawer}
            // The padding keeps a long name clear of the button next to the close button.
            title={<span className="block pr-40">{openRow?.name ?? 'Evaluation'}</span>}
            width={960}
            data-attr="evaluation-overview-drawer"
            description={
                openRow ? (
                    // The drawer's close button sits at the top right, so this sits just left of it.
                    <div className="absolute top-3 right-14">
                        <LemonButton
                            type="secondary"
                            size="small"
                            sideIcon={<IconArrowRight />}
                            to={urls.aiObservabilityEvaluation(openRow.id)}
                            data-attr="evaluation-overview-drawer-open"
                        >
                            Open evaluation
                        </LemonButton>
                    </div>
                ) : null
            }
        >
            {openRow ? <EvaluationResultExpanded row={openRow} /> : null}
        </LemonDrawer>
    )
}
