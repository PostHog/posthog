import React from 'react'
import { AlertMessage } from 'lib/components/AlertMessage'
import { pluralize } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

export interface EventBufferNoticeProps {
    /** Include extra rationale. */
    extended?: boolean
}

export function EventBufferNotice({ extended }: EventBufferNoticeProps): JSX.Element | null {
    const { preflight, eventBufferAcknowledged } = useValues(preflightLogic)
    const { acknowledgeEventBuffer } = useActions(preflightLogic)

    if (eventBufferAcknowledged || !preflight?.buffer_conversion_seconds) {
        return null
    }

    return (
        <AlertMessage type="info" style={{ marginBottom: '1rem' }} onClose={acknowledgeEventBuffer}>
            Note that some events with a never-before-seen distinct ID are deliberately delayed by{' '}
            {pluralize(preflight?.buffer_conversion_seconds, 'second')}
            {extended ? ' – this helps ensure accuracy of insights grouped by unique users' : ''}.{' '}
            <a href="TODO">Learn more about event buffering in PostHog Docs.</a>
        </AlertMessage>
    )
}
