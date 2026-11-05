import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

const MAX_LISTED_TABLES = 5

export interface WebhookNotRegisteredBannerProps {
    sourceName: string
    tableNames: string[]
    onSetUpWebhook: () => void
    onChangeSyncMethod: () => void
}

export function WebhookNotRegisteredBanner({
    sourceName,
    tableNames,
    onSetUpWebhook,
    onChangeSyncMethod,
}: WebhookNotRegisteredBannerProps): JSX.Element {
    const listed = tableNames.slice(0, MAX_LISTED_TABLES).join(', ')
    const hidden = tableNames.length - MAX_LISTED_TABLES

    return (
        <LemonBanner type="error" alignItems="start">
            <div className="flex flex-col gap-2 min-w-0 break-words">
                <div className="font-semibold">Webhook sync is not working for this source</div>
                <div>
                    Some tables use webhook sync, but this source has no active webhook. Each sync of these tables reads
                    the {sourceName} API instead. This is slower, and a sync can read the whole table each time.
                </div>
                {tableNames.length > 0 && (
                    <div className="text-xs">
                        {tableNames.length === 1 ? 'Table' : 'Tables'}: {listed}
                        {hidden > 0 ? ` and ${hidden.toLocaleString()} more` : ''}
                    </div>
                )}
                <div>Set up the webhook, or change these tables to another sync method.</div>
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="primary"
                        size="small"
                        onClick={onSetUpWebhook}
                        data-attr="source-webhook-not-registered-set-up"
                    >
                        Set up webhook
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={onChangeSyncMethod}
                        data-attr="source-webhook-not-registered-change-sync-method"
                    >
                        Change sync method
                    </LemonButton>
                </div>
            </div>
        </LemonBanner>
    )
}
