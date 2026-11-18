import { useValues } from 'kea'

import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { PAGERDUTY_REGION_OPTIONS, PAGERDUTY_SEVERITY_OPTIONS, keepsStoredKey } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'

export function PagerDutyReceiverFields(): JSX.Element {
    const { editingReceiver, receiverForm } = useValues(platformAlertRoutingLogic)
    const keepsKey = keepsStoredKey(receiverForm, editingReceiver)

    return (
        <>
            <LemonField
                name="pagerdutyRoutingKey"
                label="Integration key"
                help={
                    keepsKey
                        ? 'Leave blank to keep the current key.'
                        : 'The integration key of a PagerDuty Events API v2 integration on the service to page.'
                }
            >
                <LemonInput
                    // The key lets anyone open incidents on the service, so typed text is not captured.
                    className="ph-no-capture"
                    type="password"
                    placeholder={
                        editingReceiver?.type === 'pagerduty' ? editingReceiver.pagerduty_routing_key : undefined
                    }
                    data-attr="platform-alert-receiver-pagerduty-routing-key"
                />
            </LemonField>
            <LemonField name="pagerdutySeverity" label="Severity">
                <LemonSelect
                    options={PAGERDUTY_SEVERITY_OPTIONS}
                    fullWidth
                    data-attr="platform-alert-receiver-pagerduty-severity"
                />
            </LemonField>
            <LemonField name="pagerdutyRegion" label="Region">
                <LemonSelect
                    options={PAGERDUTY_REGION_OPTIONS}
                    fullWidth
                    data-attr="platform-alert-receiver-pagerduty-region"
                />
            </LemonField>
        </>
    )
}
