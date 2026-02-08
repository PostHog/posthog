import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { teamLogic } from 'scenes/teamLogic'

import { HogJumpGame } from './HogJumpGame'

export interface HogJumpErrorProps {
    error?: Error
    errorInfo?: React.ErrorInfo
    exceptionId?: string
    onReportError?: () => void
}

export function HogJumpError({ error, exceptionId, onReportError }: HogJumpErrorProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { openSupportForm } = useActions(supportLogic)

    const handleReportError = (): void => {
        if (onReportError) {
            onReportError()
        } else {
            openSupportForm({
                kind: 'bug',
                isEmailFormOpen: true,
            })
        }
    }

    return (
        <div className="flex flex-col items-center justify-center min-h-[400px] p-8 gap-6">
            <HogJumpGame
                isActive
                title="Oops! Something went wrong"
                subtitle={currentTeam ? 'While we fix this, why not play a game?' : undefined}
            />

            <div className="flex flex-col items-center gap-2 max-w-md text-center">
                {error && (
                    <details className="text-xs text-muted">
                        <summary className="cursor-pointer hover:text-default">View error details</summary>
                        <pre className="mt-2 p-2 bg-surface-secondary rounded text-left overflow-auto max-h-32 text-xs">
                            {error.message}
                            {error.stack && (
                                <>
                                    {'\n\n'}
                                    {error.stack}
                                </>
                            )}
                        </pre>
                    </details>
                )}

                {exceptionId && <div className="text-xs text-muted">Exception ID: {exceptionId}</div>}

                <div className="flex gap-2 mt-2">
                    <LemonButton type="secondary" size="small" onClick={() => window.location.reload()}>
                        Reload page
                    </LemonButton>
                    <LemonButton type="primary" size="small" onClick={handleReportError}>
                        Report this issue
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}

export default HogJumpError
