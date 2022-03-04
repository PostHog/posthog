import { ErrorBoundary as SentryErrorBoundary } from '@sentry/react'
import { AlertMessage } from 'lib/components/InfoMessage/AlertMessage'
import React from 'react'

export function ErrorBoundary({ children }: { children: any }): JSX.Element {
    return (
        <SentryErrorBoundary
            fallback={({ error, eventId }) => (
                <AlertMessage type="warning" style={{ marginTop: '1.5rem' }}>
                    <>
                        <p>An error has occured on this page:</p>
                        <p>
                            {error.name} (ID: {eventId}):
                            <br />
                            {error.message}
                        </p>
                        We've registered this event for analysis, but feel free to reach out directly to us too.
                        <br />
                    </>
                </AlertMessage>
            )}
        >
            {children}
        </SentryErrorBoundary>
    )
}
