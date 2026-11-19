import { useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { keepsStoredUrl } from './platformAlertRoutingFormat'
import { platformAlertRoutingLogic } from './platformAlertRoutingLogic'

export function WebhookReceiverFields(): JSX.Element {
    const { editingReceiver, receiverForm } = useValues(platformAlertRoutingLogic)
    const keepsUrl = keepsStoredUrl(receiverForm, editingReceiver)

    return (
        <LemonField
            name="webhookUrl"
            label="Webhook URL"
            help={keepsUrl ? 'Leave blank to keep the current URL.' : undefined}
        >
            <LemonInput
                // The URL's path carries the provider's secret, so copied text is not captured.
                className="ph-no-capture"
                placeholder={keepsUrl ? editingReceiver?.webhook_url : 'https://example.com/webhook'}
                data-attr="platform-alert-receiver-webhook-url"
            />
        </LemonField>
    )
}
