import { useValues } from 'kea'

import { TraceDrawerHost } from '../../redesign/trace/TraceDrawerHost'
import { SUGGESTION_EXAMPLES_LIST } from '../suggestions/evaluationSuggestionsLogic'
import { EVALUATION_OVERVIEW_TRACES, evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'

/** The page's one trace drawer. Both lists read the same URL, so only the list of the open drawer is mounted. */
export function EvaluationOverviewTraceDrawer(): JSX.Element {
    const { openEvaluationId } = useValues(evaluationResultDrawerLogic)
    return <TraceDrawerHost listId={openEvaluationId ? EVALUATION_OVERVIEW_TRACES : SUGGESTION_EXAMPLES_LIST} />
}
