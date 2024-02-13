import './ErrorBoundary.scss'

import { IconChevronDown } from '@posthog/icons'
import { ErrorBoundary as SentryErrorBoundary, getCurrentHub } from '@sentry/react'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

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
                                <LemonButton type="primary" sideIcon={<IconChevronDown />}>
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
