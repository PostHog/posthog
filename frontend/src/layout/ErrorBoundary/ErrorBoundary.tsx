import './ErrorBoundary.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

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

/**
 * These throw when something outside React rewrites DOM that React is holding on to, which in
 * practice means in-page translation replacing text nodes with `<font>` wrappers. Most of them
 * never reach a boundary, because `installTranslationSafeDom` neutralizes the two mutators
 * React's commit phase relies on; this branch covers whatever still gets through.
 */
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
    // PostHogErrorBoundary keeps the caught error in its own state and exposes no reset, so
    // remounting it is the only route back to rendering children. Without this, the app-root
    // boundary in scenes/App.tsx is terminal: it has no key that ever changes, unlike the
    // per-scene boundary that resets whenever the scene does, so anything thrown from the nav
    // or the command palette leaves a page reload as the user's only way out.
    const [resetCount, setResetCount] = useState(0)

    const additionalProperties = { ...exceptionProps }

    if (currentTeamId !== undefined) {
        additionalProperties.team_id = currentTeamId
    }

    return (
        <PostHogErrorBoundary
            key={resetCount}
            additionalProperties={additionalProperties}
            fallback={(props: PostHogErrorBoundaryFallbackProps) => {
                const rawError = props.error
                const normalizedError =
                    rawError instanceof Error
                        ? rawError
                        : new Error(typeof rawError === 'string' ? rawError : 'Unknown error')
                const { stack, name, message } = normalizedError

                const exceptionEvent = props.exceptionEvent as SupportTicketExceptionEvent

                const isPageRewrittenError = isDOMModificationError(normalizedError)

                const errorDetails = [
                    exceptionEvent?.uuid ? `Exception ID: ${exceptionEvent.uuid}` : null,
                    stack || (name || message ? `${name}: ${message}` : null),
                ]
                    .filter(Boolean)
                    .join('\n\n')

                return (
                    <div className={clsx('ErrorBoundary', className)}>
                        <h2>An error has occurred</h2>
                        {isPageRewrittenError && (
                            <LemonBanner type="warning" className="mb-2">
                                Something outside PostHog rewrote the text on this page, so PostHog could no longer
                                update it. This is usually page translation, either your browser's built-in translation
                                or an extension that translates or rewrites text. Turn translation off for this site,
                                then try again.
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
                        <p className="mb-2">
                            Try again first. If the error comes back, send it to an engineer.{' '}
                            {exceptionEvent
                                ? "We'll attach the exception ID, stack trace, and session replay automatically"
                                : "We'll attach the session replay automatically"}
                            , so you only need to tell us what you were doing. Add a screenshot if you think it will
                            help.
                        </p>
                        <div className="flex gap-2 flex-wrap">
                            <LemonButton
                                type="primary"
                                center
                                onClick={() => setResetCount((count) => count + 1)}
                                className="flex-1"
                            >
                                Try again
                            </LemonButton>
                            <LemonButton
                                type="secondary"
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
