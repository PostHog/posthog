import { ErrorBoundary as SentryErrorBoundary } from '@sentry/react'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { IconArrowDropDown } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import React from 'react'
import './ErrorBoundary.scss'

export function ErrorBoundary({ children }: { children: React.ReactElement }): JSX.Element {
    return (
        <SentryErrorBoundary
            fallback={({ error, eventId }) => (
                <div className="ErrorBoundary">
                    <>
                        <h2>An error has occurred</h2>
                        <pre>
                            <code>
                                {error.name} (ID {eventId})
                                <br />
                                {error.message}
                            </code>
                        </pre>
                        We've registered this event for analysis, but feel free to contact us directly too.
                        <HelpButton
                            customComponent={
                                <LemonButton type="primary" sideIcon={<IconArrowDropDown />}>
                                    Contact PostHog
                                </LemonButton>
                            }
                            customKey="error-boundary"
                            contactOnly
                        />
                    </>
                </div>
            )}
        >
            {children}
        </SentryErrorBoundary>
    )
}
