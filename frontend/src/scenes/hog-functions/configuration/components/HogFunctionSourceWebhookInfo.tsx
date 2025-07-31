import { useValues } from 'kea'
import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'

export function HogFunctionSourceWebhookInfo(): JSX.Element {
    const { logicProps } = useValues(hogFunctionConfigurationLogic)
    const { id } = logicProps
    return (
        <div className="p-3 rounded border deprecated-space-y-2 bg-surface-primary">
            <LemonLabel>Webhook URL</LemonLabel>
            <CodeSnippet thing="Webhook URL">
                {!id ? 'The webhook URL will be shown here once you save' : apiHostOrigin() + '/public/webhooks/' + id}
            </CodeSnippet>

            <p className="text-sm">
                Use this URL in your external system to send events to PostHog. The webhook can be called with a POST
                request and any JSON payload. You can then use the configuration options to parse the{' '}
                <code>request.body</code> or <code>request.headers</code> to map to the required fields.
            </p>
        </div>
    )
}
