import { useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { keepsStoredKey } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'

export function IncidentIoReceiverFields(): JSX.Element {
    const { editingReceiver, receiverForm } = useValues(platformAlertRoutingLogic)
    const keepsKey = keepsStoredKey(receiverForm, editingReceiver)

    return (
        <>
            <LemonField
                name="incidentIoAlertSourceConfigId"
                label="Alert source ID"
                help="The last part of the HTTP alert source's URL in incident.io."
            >
                <LemonInput
                    placeholder="01GW2G3V0S59R238FAHPDS1R66"
                    data-attr="platform-alert-receiver-incident-io-alert-source"
                />
            </LemonField>
            <LemonField
                name="incidentIoSecret"
                label="Secret"
                help={
                    keepsKey
                        ? 'Leave blank to keep the current secret.'
                        : 'The secret incident.io shows for the HTTP alert source.'
                }
            >
                <LemonInput
                    // The secret lets anyone send alerts to the source, so typed text is not captured.
                    className="ph-no-capture"
                    type="password"
                    placeholder={
                        editingReceiver?.type === 'incident_io' ? editingReceiver.incident_io_secret : undefined
                    }
                    data-attr="platform-alert-receiver-incident-io-secret"
                />
            </LemonField>
        </>
    )
}
