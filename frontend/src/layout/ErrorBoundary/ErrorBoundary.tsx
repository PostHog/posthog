import './ErrorBoundary.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { PostHogErrorBoundary, type PostHogErrorBoundaryFallbackProps } from '@posthog/react'

import { SupportTicketExceptionEvent, supportLogic } from 'lib/components/Support/supportLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { teamLogic } from 'scenes/teamLogic'

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

export function ErrorBoundary({ children, exceptionProps = {}, className }: ErrorBoundaryProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { openSupportForm } = useActions(supportLogic)

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

                const exceptionEvent = props.exceptionEvent as SupportTicketExceptionEvent

                const isBrowserExtensionError = isDOMModificationError(normalizedError)

                const errorDetails = [
                    exceptionEvent?.uuid ? `Exception ID: ${exceptionEvent.uuid}` : null,
                    stack || (name || message ? `${name}: ${message}` : null),
                ]
                    .filter(Boolean)
                    .join('\n\n')

                return (
                    <div className={clsx('ErrorBoundary', className)}>
                        <h2>An error has occurred</h2>
                        {isBrowserExtensionError && (
                            <LemonBanner
                                type="warning"
                                className="mb-2"
                                action={{
                                    children: 'Email an engineer',
                                    onClick: () => {
                                        openSupportForm({
                                            kind: 'bug',
                                            isEmailFormOpen: true,
                                            exception_event: exceptionEvent ?? null,
                                        })
                                    },
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
                        {!isBrowserExtensionError && (
                            <>
                                <p className="mb-2">
                                    Click below to send this to an engineer.{' '}
                                    {exceptionEvent
                                        ? "We'll attach the exception ID, stack trace, and session replay automatically"
                                        : "We'll attach the session replay automatically"}{' '}
                                    — just tell us what you were doing, and add a screenshot if you think it will help.
                                </p>
                                <div className="flex gap-2 flex-wrap">
                                    <LemonButton
                                        type="primary"
                                        center
                                        onClick={() => {
                                            openSupportForm({
                                                kind: 'bug',
                                                isEmailFormOpen: true,
                                                exception_event: exceptionEvent ?? null,
                                            })
                                        }}
                                        className="flex-1"
                                    >
                                        Email an engineer
                                    </LemonButton>
                                    <LemonButton
                                        type="secondary"
                                        center
                                        icon={<IconCopy />}
                                        onClick={() => void copyToClipboard(errorDetails, 'error details')}
                                        disabledReason={!errorDetails ? 'No details to copy' : undefined}
                                        className="flex-1"
                                    >
                                        Copy error details
                                    </LemonButton>
                                </div>
                            </>
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
