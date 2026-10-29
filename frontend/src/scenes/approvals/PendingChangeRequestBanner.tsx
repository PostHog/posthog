import { useActions, useValues } from 'kea'

import { ChangeRequestBanner } from './ChangeRequestBanner'
import { ChangeRequestsLogicProps, changeRequestsLogic } from './changeRequestsLogic'

export function PendingChangeRequestBanner(props: ChangeRequestsLogicProps): JSX.Element | null {
    const logic = changeRequestsLogic(props)
    const { pendingChangeRequest, shouldShowBanner, actionInFlight } = useValues(logic)
    const { approveRequest, rejectRequest, cancelRequest } = useActions(logic)

    if (!shouldShowBanner || !pendingChangeRequest) {
        return null
    }

    return (
        <ChangeRequestBanner
            changeRequest={pendingChangeRequest}
            context={props.context}
            onApprove={(id) => approveRequest(id)}
            onReject={(id, reason) => rejectRequest(id, reason)}
            onCancel={(id, reason) => cancelRequest(id, reason)}
            actionInFlight={actionInFlight?.id === pendingChangeRequest.id ? actionInFlight.action : null}
        />
    )
}
