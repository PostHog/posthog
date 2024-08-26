import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { QueryBasedInsightModel } from '~/types'

import { AlertsLogicProps, areAlertsSupportedForInsight } from './alertsLogic'
import { EditAlert } from './views/EditAlert'
import { ManageAlerts } from './views/ManageAlerts'

export interface AlertsModalProps extends AlertsLogicProps {
    isOpen: boolean
    closeModal: () => void
    alertId: number | 'new' | null
}

export function AlertsModal(props: AlertsModalProps): JSX.Element {
    const { closeModal, insightShortId, insightLogicProps, alertId, isOpen } = props
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
                    insightLogicProps={insightLogicProps}
                    onCancel={closeModal}
                    onSelect={(id) => push(urls.alert(insightShortId, id.toString()))}
                />
            ) : (
                <EditAlert
                    id={alertId}
                    insightShortId={insightShortId}
                    insightLogicProps={insightLogicProps}
                    onCancel={() => push(urls.alerts(insightShortId))}
                    onDelete={() => push(urls.alerts(insightShortId))}
                />
            )}
        </LemonModal>
    )
}

export interface AlertsButtonProps {
    insight: Partial<QueryBasedInsightModel>
}

export function AlertsButton({ insight }: AlertsButtonProps): JSX.Element {
    const { push } = useActions(router)
    const { featureFlags } = useValues(featureFlagLogic)
    const showAlerts = featureFlags[FEATURE_FLAGS.ALERTS]

    if (!showAlerts) {
        return <></>
    }
    if (!areAlertsSupportedForInsight(insight.query)) {
        return (
            <LemonButton
                data-attr="disabled-alerts-button"
                disabledReason="Insights are only availabe for trends represented as a number. Change the insight representation to add alerts."
            >
                Alerts
            </LemonButton>
        )
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
                        <LemonButton onClick={() => push(urls.alert(insight.short_id!, 'new'))} fullWidth>
                            New alert
                        </LemonButton>
                        <LemonButton onClick={() => push(urls.alerts(insight.short_id!))} fullWidth>
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
