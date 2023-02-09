import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { pluralize } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export interface EventBufferNoticeProps {
    additionalInfo?: string
    className?: string
}

export function EventBufferNotice({ additionalInfo, className }: EventBufferNoticeProps): JSX.Element | null {
    const { preflight, eventBufferAcknowledged } = useValues(preflightLogic)
    const { acknowledgeEventBuffer } = useActions(preflightLogic)

    if (eventBufferAcknowledged || !preflight?.buffer_conversion_seconds) {
        return null
    }

    return (
        <AlertMessage type="info" onClose={acknowledgeEventBuffer} className={className}>
            Note that some events with a never-before-seen distinct ID are deliberately delayed by{' '}
            {pluralize(preflight?.buffer_conversion_seconds, 'second')}
            {additionalInfo}.{' '}
            <a href="https://posthog.com/docs/integrate/ingest-live-data#event-ingestion-nuances">
                Learn more about event buffering in PostHog Docs.
            </a>
        </AlertMessage>
    )
}
