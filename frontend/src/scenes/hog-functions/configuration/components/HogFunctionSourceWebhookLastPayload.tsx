import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonSkeleton } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { TZLabel } from 'lib/components/TZLabel'

import { hogFunctionSourceWebhookLastPayloadLogic } from './hogFunctionSourceWebhookLastPayloadLogic'

export function HogFunctionSourceWebhookLastPayload({ id }: { id: string }): JSX.Element {
    const logic = hogFunctionSourceWebhookLastPayloadLogic({ id })
    const { lastPayload, lastPayloadLoading } = useValues(logic)
    const { loadLastPayload } = useActions(logic)

    return (
        <div className="p-3 rounded border deprecated-space-y-2 bg-surface-primary">
            <div className="flex flex-wrap gap-2 justify-between items-center">
                <LemonLabel>Last received payload</LemonLabel>
                <LemonButton
                    size="small"
                    icon={<IconRefresh />}
                    onClick={loadLastPayload}
                    loading={lastPayloadLoading}
                    data-attr="hog-function-source-webhook-last-payload-refresh"
                >
                    Refresh
                </LemonButton>
            </div>
            {lastPayloadLoading && !lastPayload ? (
                <LemonSkeleton className="h-12" />
            ) : lastPayload ? (
                <>
                    <p className="text-sm text-secondary">
                        Received <TZLabel time={lastPayload.timestamp} />
                    </p>
                    <CodeSnippet thing="Payload" language={Language.JSON} maxLinesWithoutExpansion={20}>
                        {lastPayload.payload}
                    </CodeSnippet>
                    <p className="text-sm">
                        Use <code>request.body</code> to map these fields.
                    </p>
                </>
            ) : (
                <p className="text-sm">
                    No payload received in the last 7 days. Turn on <b>Log payloads</b>, save, and send a request to the
                    webhook URL. The payload then shows here.
                </p>
            )}
        </div>
    )
}
