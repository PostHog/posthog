import { DataQualityCheckEditorLogicProps } from '../dataQualityCheckEditorLogic'
import { NEW_CHECK_ACTION_ID, OverviewRunTarget, rowActionsId, subjectKeyOf } from './dataQualityOverviewLogic'
import { focusFirstAvailable } from './focusFirstAvailable'

export function overviewCheckEditorProps({
    lastActionCheckId,
    loadOverview,
    runChecks,
}: {
    lastActionCheckId: string | null
    loadOverview: () => void
    runChecks: (target: OverviewRunTarget, checkIds?: string[]) => void
}): DataQualityCheckEditorLogicProps {
    return {
        surface: 'data-quality-overview',
        onSaved: () => loadOverview(),
        onRunNow: (check) =>
            runChecks({ kind: 'subject', subjectKey: subjectKeyOf(check.subject_type, check.subject_uuid) }, [
                check.id,
            ]),
        onClosed: () => {
            if (lastActionCheckId) {
                focusFirstAvailable([rowActionsId(lastActionCheckId)])
            } else {
                focusFirstAvailable([NEW_CHECK_ACTION_ID])
            }
        },
    }
}
