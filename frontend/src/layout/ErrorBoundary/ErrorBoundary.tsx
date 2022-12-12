import { getCurrentHub, ErrorBoundary as SentryErrorBoundary } from '@sentry/react'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { IconArrowDropDown } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import './ErrorBoundary.scss'

export function ErrorBoundary({ children }: { children: React.ReactElement }): JSX.Element {
    const isSentryInitialized = !!getCurrentHub().getClient()

    return (
        <SentryErrorBoundary
            fallback={({ error, eventId }) => (
                <div className="ErrorBoundary">
                    <>
                        <h2>An error has occurred</h2>
                        <pre>
                            <code>
                                {error.stack || (
                                    <>
                                        {error.name}
                                        <br />
                                        {error.message}
                                    </>
                                )}
                            </code>
                        </pre>
                        {isSentryInitialized
                            ? `We've registered this event for analysis (ID ${eventId}), but feel free to contact us directly too.`
                            : 'Please send over a screenshot of this message, so that we can resolve the issue.'}
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
