import './ErrorBoundary.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PostHogErrorBoundary, type PostHogErrorBoundaryFallbackProps } from 'posthog-js/react'

import { SupportTicketExceptionEvent, supportLogic } from 'lib/components/Support/supportLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ICONS } from 'lib/integrations/utils'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { teamLogic } from 'scenes/teamLogic'

import { errorBoundaryLinkedIssueLogic } from './errorBoundaryLinkedIssueLogic'

const DOM_MUTATION_PATTERNS = [
    "Failed to execute 'removeChild' on 'Node'",
    "Failed to execute 'insertBefore' on 'Node'",
    "Failed to execute 'appendChild' on 'Node'",
]

function isDOMModificationError(error: Error): boolean {
    const message = error.message || ''
    return DOM_MUTATION_PATTERNS.some((pattern) => message.includes(pattern))
}

interface ErrorBoundaryProps {
    children?: React.ReactNode
    exceptionProps?: Record<string, number | string | boolean | bigint | symbol | null | undefined>
    className?: string
}

function LinkedIssueDisplay({
    eventUuid,
    timestamp,
    onEmailEngineer,
}: {
    eventUuid: string
    timestamp: string
    onEmailEngineer: () => void
}): JSX.Element | null {
    const { externalUrls, polling, timedOut } = useValues(errorBoundaryLinkedIssueLogic({ eventUuid, timestamp }))

    const docsLink = 'https://posthog.com/docs/error-tracking/fingerprints'

    if (polling) {
        return (
            <div className="my-3 p-3 rounded border space-y-1">
                <div className="flex items-center gap-2 font-semibold">
                    <Spinner className="text-lg" />
                    Checking PostHog Error Tracking for a linked issue...
                </div>
                <p className="text-muted text-xs mb-2">
                    We use{' '}
                    <Link to={docsLink} target="_blank" className="text-link">
                        PostHog Error Tracking
                    </Link>{' '}
                    to group errors into issues. This can take a moment while we fingerprint the error.
                </p>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onEmailEngineer}
                    className="mt-1"
                    data-ph-capture-attribute-error-boundary-interaction="email-engineer-polling"
                >
                    Email an engineer
                </LemonButton>
            </div>
        )
    }

    if (timedOut || externalUrls.length === 0) {
        return (
            <div className="my-3 p-3 rounded border space-y-3">
                <p className="text-muted text-sm mb-2">No public issue found for this error.</p>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onEmailEngineer}
                    data-ph-capture-attribute-error-boundary-interaction="email-engineer-timed-out"
                >
                    Email an engineer
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="my-3 p-3 rounded border flex items-center gap-2 flex-wrap">
            {externalUrls.map((externalUrl) => (
                <LemonButton
                    key={externalUrl.url}
                    type="primary"
                    size="small"
                    to={externalUrl.url}
                    targetBlank
                    tooltip="Track this issue on GitHub. Add any extra context about what you were doing when the crash happened in the issue comments!"
                    icon={<img src={ICONS.github} className="w-4 h-4 rounded-sm" />}
                    data-ph-capture-attribute-error-boundary-interaction="track-github"
                >
                    Track via GitHub
                </LemonButton>
            ))}
            <span className="text-muted text-sm">or</span>
            <LemonButton
                type="secondary"
                size="small"
                onClick={onEmailEngineer}
                data-ph-capture-attribute-error-boundary-interaction="email-engineer-linked-issue"
            >
                Email an engineer
            </LemonButton>
        </div>
    )
}

export function ErrorBoundary({ children, exceptionProps = {}, className }: ErrorBoundaryProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { openSupportForm } = useActions(supportLogic)
    const showLinkedIssue = useFeatureFlag('ERROR_BOUNDARY_ISSUE_LINK', 'test')

    const additionalProperties: ErrorBoundaryProps['exceptionProps'] = {
        ...exceptionProps,
        is_error_boundary_error: true,
    }

    if (currentTeamId !== undefined) {
        additionalProperties.team_id = currentTeamId
    }

    return (
        <PostHogErrorBoundary
            additionalProperties={additionalProperties}
            fallback={(props: PostHogErrorBoundaryFallbackProps) => {
                const rawError = props.error
                const normalizedError =
                    rawError instanceof Error
                        ? rawError
                        : new Error(typeof rawError === 'string' ? rawError : 'Unknown error')
                const { stack, name, message } = normalizedError

                const exceptionEvent = props.exceptionEvent as SupportTicketExceptionEvent

                const isBrowserExtensionError = isDOMModificationError(normalizedError)

                const emailEngineer = (): void => {
                    openSupportForm({
                        kind: 'bug',
                        isEmailFormOpen: true,
                        exception_event: exceptionEvent ?? null,
                    })
                }

                return (
                    <div className={clsx('ErrorBoundary', className)}>
                        <h2>An error has occurred</h2>
                        {isBrowserExtensionError && (
                            <LemonBanner
                                type="warning"
                                className="mb-2"
                                action={{
                                    children: 'Email an engineer',
                                    onClick: emailEngineer,
                                }}
                            >
                                This error is commonly caused by browser extensions (such as translation or ad-blocking
                                extensions) that modify the page. Try disabling your browser extension(s) and reloading
                                the page to avoid this error in the future.
                            </LemonBanner>
                        )}
                        <pre>
                            <code>
                                {stack || (
                                    <>
                                        {name}
                                        <br />
                                        {message}
                                    </>
                                )}
                            </code>
                        </pre>
                        {exceptionEvent?.uuid && (
                            <div className="text-muted text-xs mb-2">Exception ID: {exceptionEvent.uuid}</div>
                        )}
                        {showLinkedIssue && exceptionEvent?.uuid ? (
                            <LinkedIssueDisplay
                                eventUuid={exceptionEvent.uuid}
                                timestamp={new Date().toISOString()}
                                onEmailEngineer={emailEngineer}
                            />
                        ) : (
                            !isBrowserExtensionError && (
                                <>
                                    Please help us resolve the issue by sending a screenshot of this message.
                                    <LemonButton
                                        type="primary"
                                        fullWidth
                                        center
                                        onClick={emailEngineer}
                                        targetBlank
                                        className="mt-2"
                                        data-ph-capture-attribute-error-boundary-interaction="email-engineer-control"
                                    >
                                        Email an engineer
                                    </LemonButton>
                                </>
                            )
                        )}
                    </div>
                )
            }}
        >
            {children}
        </PostHogErrorBoundary>
    )
}

export function LightErrorBoundary({ children, exceptionProps = {}, className }: ErrorBoundaryProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const additionalProperties = { ...exceptionProps }
    if (currentTeamId !== undefined) {
        additionalProperties.team_id = currentTeamId
    }
    return (
        <PostHogErrorBoundary
            additionalProperties={additionalProperties}
            fallback={(props: PostHogErrorBoundaryFallbackProps) => {
                const rawError = props.error
                const normalizedError =
                    rawError instanceof Error
                        ? rawError
                        : new Error(typeof rawError === 'string' ? rawError : 'Unknown error')
                const { stack, name, message } = normalizedError
                return (
                    <div className={clsx('text-danger', className)}>
                        {stack || (name || message ? `${name}: ${message}` : 'Error')}
                    </div>
                )
            }}
        >
            {children}
        </PostHogErrorBoundary>
    )
}
