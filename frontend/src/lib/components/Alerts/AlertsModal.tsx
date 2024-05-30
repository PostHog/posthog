import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { InsightShortId } from '~/types'

import { EditAlert } from './views/EditAlert'
import { ManageAlerts } from './views/ManageAlerts'

export interface AlertsModalProps {
    isOpen: boolean
    closeModal: () => void
    alertId: number | 'new' | null
    insightShortId: InsightShortId
}

export function AlertsModal(props: AlertsModalProps): JSX.Element {
    const { closeModal, insightShortId, alertId, isOpen } = props
    const { push } = useActions(router)
    const { userLoading } = useValues(userLogic)

    if (userLoading) {
        return <Spinner className="text-2xl" />
    }
    return (
        <LemonModal onClose={closeModal} isOpen={isOpen} width={600} simple title="">
            {!alertId ? (
                <ManageAlerts
                    insightShortId={insightShortId}
                    onCancel={closeModal}
                    onSelect={(id) => push(urls.alert(insightShortId, id.toString()))}
                />
            ) : (
                <EditAlert
                    id={alertId}
                    insightShortId={insightShortId}
                    onCancel={() => push(urls.alerts(insightShortId))}
                    onDelete={() => push(urls.alerts(insightShortId))}
                />
            )}
        </LemonModal>
    )
}

export interface AlertsButtonProps {
    insightShortId: InsightShortId
}

export function AlertsButton({ insightShortId }: AlertsButtonProps): JSX.Element {
    const { push } = useActions(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const showAlerts = featureFlags[FEATURE_FLAGS.ALERTS]

    if (!showAlerts) {
        return <></>
    }
    return (
        <LemonButtonWithDropdown
            fullWidth
            dropdown={{
                actionable: true,
                closeParentPopoverOnClickInside: true,
                placement: 'right-start',
                overlay: (
                    <>
                        <LemonButton onClick={() => push(urls.alert(insightShortId, 'new'))} fullWidth>
                            New alert
                        </LemonButton>
                        <LemonButton onClick={() => push(urls.alerts(insightShortId))} fullWidth>
                            Manage alerts
                        </LemonButton>
                    </>
                ),
            }}
        >
            Alerts
        </LemonButtonWithDropdown>
    )
}
