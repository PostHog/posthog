import { ErrorBoundary as SentryErrorBoundary } from '@sentry/react'
import { AlertMessage } from 'lib/components/InfoMessage/AlertMessage'
import React from 'react'

export function ErrorBoundary({ children }: { children: React.ReactElement }): JSX.Element {
    return (
        <SentryErrorBoundary
            fallback={({ error, eventId }) => (
                <AlertMessage type="warning" style={{ marginTop: '1.5rem' }}>
                    <>
                        <p>Oh no! An error has occured:</p>
                        <p>
                            {error.name} (ID {eventId})
                            <br />
                            {error.message}
                        </p>
                        We've registered this event for analysis, but feel free to contact us directly too.
                        <br />
                    </>
                </AlertMessage>
            )}
        >
            {children}
        </SentryErrorBoundary>
    )
}
