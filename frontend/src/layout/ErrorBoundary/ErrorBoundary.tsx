import './ErrorBoundary.scss'

import { ErrorBoundary as SentryErrorBoundary, getCurrentHub } from '@sentry/react'
import type { Primitive } from '@sentry/types'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { teamLogic } from 'scenes/teamLogic'

interface ErrorBoundaryProps {
    children?: React.ReactNode
    tags?: Record<string, Primitive>
}

export function ErrorBoundary({ children, tags = {} }: ErrorBoundaryProps): JSX.Element {
    const isSentryInitialized = !!getCurrentHub().getClient()
    const { currentTeamId } = useValues(teamLogic)
    const { openSupportForm } = useActions(supportLogic)

    return (
        <SentryErrorBoundary
            beforeCapture={(scope) => {
                if (currentTeamId !== undefined) {
                    scope.setTag('team_id', currentTeamId)
                }
                scope.setTags(tags)
            }}
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
