import { LemonCollapse } from '@posthog/lemon-ui'
import { pluralize } from 'lib/utils'

import { FeatureFlagType, WebhookSubscription } from '~/types'

interface ReadOnlyWebhookCardProps {
    subscription: WebhookSubscription
}

function ReadOnlyWebhookCard({ subscription }: ReadOnlyWebhookCardProps): JSX.Element {
    const headersLen = Object.keys(subscription.headers || {}).length
    return (
        <div className="p-3 border rounded bg-bg-light">
            <div className="flex items-start justify-between">
                <div className="flex-1">
                    <div className="font-mono text-sm break-all mb-2">{subscription.url}</div>
                    {subscription.headers && headersLen > 0 && (
                        <LemonCollapse
                            panels={[
                                {
                                    key: 'headers',
                                    header: pluralize(headersLen, 'custom header'),
                                    content: (
                                        <div className="space-y-1">
                                            {Object.entries(subscription.headers).map(([key, value]) => (
                                                <div key={key} className="flex gap-2 text-sm">
                                                    <span className="font-semibold text-muted flex-shrink-0">
                                                        {key}:
                                                    </span>
                                                    <span className="font-mono break-all overflow-hidden">{value}</span>
                                                </div>
                                            ))}
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    )}
                </div>
            </div>
        </div>
    )
}

export function FeatureFlagSubscribeTab({ featureFlag }: { featureFlag: FeatureFlagType }): JSX.Element {
    const webhookSubscriptions = featureFlag.webhook_subscriptions || []

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold mb-2">Webhook Subscriptions</h3>
                <p className="text-muted text-sm mb-4">
                    Webhook URLs that receive notifications when this feature flag changes.
                </p>
            </div>

            {/* List of webhook subscriptions (read-only) */}
            {webhookSubscriptions.length > 0 && (
                <div>
                    <h4 className="text-base font-medium mb-2">Configured Webhooks</h4>
                    <div className="space-y-2">
                        {webhookSubscriptions.map((subscription) => (
                            <ReadOnlyWebhookCard key={subscription.url} subscription={subscription} />
                        ))}
                    </div>
                </div>
            )}

            {webhookSubscriptions.length === 0 && (
                <div className="text-center py-8 text-muted">
                    <p>No webhooks configured.</p>
                    <p className="text-sm">Configure webhooks when editing this feature flag.</p>
                </div>
            )}
        </div>
    )
}
