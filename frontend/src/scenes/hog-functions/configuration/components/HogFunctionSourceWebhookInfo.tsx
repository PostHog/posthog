import { useValues } from 'kea'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'

import { hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'

export function HogFunctionSourceWebhookInfo(): JSX.Element {
    const { logicProps } = useValues(hogFunctionConfigurationLogic)
    const { id } = logicProps
    return (
        <div className="p-3 rounded border deprecated-space-y-2 bg-surface-primary">
            <LemonLabel>Webhook URL</LemonLabel>
            <CodeSnippet thing="Webhook URL">
                {!id
                    ? 'The webhook URL will be shown here once you save'
                    : publicWebhooksHostOrigin() + '/public/webhooks/' + id}
            </CodeSnippet>

            <p className="text-sm">
                Use this URL in your external system to send events to PostHog. The webhook can be called with a POST
                request and any JSON payload, or a GET request. You can also use extensions such as <code>.gif</code>{' '}
                for embedding the webhook as an image for example in an email.
            </p>

            <p className="text-sm">
                You can then use the configuration options to parse the <code>request.body</code> or{' '}
                <code>request.headers</code> or <code>request.query</code> to map to the required fields.
            </p>
        </div>
    )
}
