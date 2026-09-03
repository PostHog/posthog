import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { IconRefresh } from '@posthog/icons'

import { SupportTicketExceptionEvent, supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { teamLogic } from 'scenes/teamLogic'

interface AppLoadErrorProps {
    error: unknown
}

/**
 * Shown when the app shell chunk still fails to download after the automatic retries and reload.
 * The generic ErrorBoundary never sees this error, so the exception is captured here to keep it
 * visible in error tracking.
 */
export function AppLoadError({ error }: AppLoadErrorProps): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)
    const { currentTeamId } = useValues(teamLogic)
    const [exceptionEvent, setExceptionEvent] = useState<SupportTicketExceptionEvent | undefined>()

    // Capture once per mount. A re-render must not send the same failure again.
    useEffect(() => {
        setExceptionEvent(posthog.captureException(error, { chunk_load_error: true, team_id: currentTeamId }))
    }, []) // oxlint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="p-4">
            <h1 className="mb-1 text-2xl font-bold">PostHog could not load</h1>
            <p>
                Your browser could not download part of the app. This is usually a network problem. Reload the page to
                try again. If it happens again, try a different network, or turn off browser extensions and proxies.
            </p>
            <div className="flex gap-2 flex-wrap">
                <LemonButton
                    type="primary"
                    icon={<IconRefresh />}
                    onClick={() => window.location.reload()}
                    data-attr="app-load-error-reload"
                >
                    Reload the page
                </LemonButton>
                <LemonButton
                    type="secondary"
                    onClick={() =>
                        openSupportForm({ kind: 'bug', isEmailFormOpen: true, exception_event: exceptionEvent })
                    }
                    data-attr="app-load-error-email-engineer"
                >
                    Email an engineer
                </LemonButton>
            </div>
            {exceptionEvent?.uuid && <div className="text-muted text-xs mt-2">Exception ID: {exceptionEvent.uuid}</div>}
        </div>
    )
}
