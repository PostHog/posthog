import './ErrorBoundary.scss'

import { ErrorBoundary as SentryErrorBoundary, getCurrentHub } from '@sentry/react'
import { useActions } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

export function ErrorBoundary({ children }: { children?: React.ReactNode }): JSX.Element {
    const isSentryInitialized = !!getCurrentHub().getClient()
    const { openSupportForm } = useActions(supportLogic)

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
                        {isSentryInitialized && eventId?.match(/[^0]/)
                            ? `We've registered this event for analysis (ID ${eventId}), but feel free to contact us directly too.`
                            : 'Please help us resolve the issue by sending a screenshot of this message.'}
                        <LemonButton
                            type="primary"
                            fullWidth
                            center
                            onClick={() => openSupportForm({ kind: 'bug', isEmailFormOpen: true })}
                            targetBlank
                            className="mt-2"
                        >
                            Email an engineer
                        </LemonButton>
                    </>
                </div>
            )}
        >
            {children}
        </SentryErrorBoundary>
    )
}
