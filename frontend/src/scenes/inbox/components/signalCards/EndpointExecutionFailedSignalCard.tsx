import { combineUrl } from 'kea-router'

import { IconWarning } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import type { EndpointExecutionFailedSignalExtra } from '~/queries/schema/schema-signals'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a signal's `extra` to the endpoint execution failure shape. */
export function isEndpointExecutionFailedExtra(
    extra: Record<string, unknown>
): extra is Record<string, unknown> & EndpointExecutionFailedSignalExtra {
    return typeof extra.endpoint_name === 'string' && typeof extra.error_class === 'string'
}

/** Inbox signal card for a failed endpoint execution: endpoint identity, error class, and the error message. */
export function EndpointExecutionFailedSignalCard({ signal }: SignalCardProps): JSX.Element {
    const extra: EndpointExecutionFailedSignalExtra | null = isEndpointExecutionFailedExtra(signal.extra)
        ? signal.extra
        : null

    if (!extra) {
        return <SignalCardShell signal={signal}>{null}</SignalCardShell>
    }

    const { endpoint_name, endpoint_version, materialized, error_class, error_message } = extra
    const endpointUrl = urls.endpoint(endpoint_name, endpoint_version ?? undefined)
    const logsUrl = combineUrl(endpointUrl, { tab: 'logs' }).url

    return (
        <SignalCardShell signal={signal}>
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{endpoint_name}</span>
                {endpoint_version != null && <LemonTag size="small">v{endpoint_version}</LemonTag>}
                {materialized && <LemonTag size="small">Materialized</LemonTag>}
            </div>

            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mt-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            <div className="mt-2">
                <LemonTag type="danger" size="small" icon={<IconWarning />}>
                    {error_class}
                </LemonTag>
            </div>

            {error_message && (
                <div className="mt-2">
                    <CodeSnippet
                        language={Language.Text}
                        wrap
                        compact
                        maxLinesWithoutExpansion={6}
                        thing="error message"
                    >
                        {error_message}
                    </CodeSnippet>
                </div>
            )}

            <div className="flex items-center gap-3 text-xs mt-2">
                <span className="flex-1" />
                <Link to={endpointUrl} className="font-medium">
                    View endpoint
                </Link>
                <Link to={logsUrl} className="font-medium">
                    View execution logs
                </Link>
            </div>
        </SignalCardShell>
    )
}

export const endpointExecutionFailedSignalCardEntry: SignalCardEntry = {
    key: 'endpoints',
    matches: (signal: SignalNode) =>
        signal.source_product === 'endpoints' && isEndpointExecutionFailedExtra(signal.extra),
    Component: EndpointExecutionFailedSignalCard,
}
