import React from 'react'
import { AlertMessage } from 'lib/components/AlertMessage'
import { pluralize } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export interface EventBufferNoticeProps {
    /** Include extra rationale. */
    additionalInfo?: string
    style?: Record<string, string | number>
}

export function EventBufferNotice({ additionalInfo = '', style = {} }: EventBufferNoticeProps): JSX.Element | null {
    const { preflight, eventBufferAcknowledged } = useValues(preflightLogic)
    const { acknowledgeEventBuffer } = useActions(preflightLogic)

    if (eventBufferAcknowledged || !preflight?.buffer_conversion_seconds) {
        return null
    }

    return (
        <AlertMessage type="info" style={{ marginBottom: '1rem', ...style }} onClose={acknowledgeEventBuffer}>
            Note that some events with a never-before-seen distinct ID are deliberately delayed by{' '}
            {pluralize(preflight?.buffer_conversion_seconds, 'second')}
            {additionalInfo}.{' '}
            <a href="https://posthog.com/docs/integrate/ingest-live-data/#event-ingestion-nuances">
                Learn more about event buffering in PostHog Docs.
            </a>
        </AlertMessage>
    )
}
