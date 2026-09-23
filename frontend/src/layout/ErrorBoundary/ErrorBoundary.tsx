import './ErrorBoundary.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect, useRef, useState } from 'react'

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
 * These throw when something outside React rewrites DOM that React still holds, which in practice
 * means in-page translation that replaces text nodes with `<font>` wrappers (react#11538). Render
 * sites can opt out of translation to stop the shape at the source, but `{cond && 'text'}` is
 * common all over the app, so this branch is what keeps the untreated ones from costing a scene.
 */
function isDOMModificationError(error: Error): boolean {
    const message = error.message || ''
    return DOM_MUTATION_PATTERNS.some((pattern) => message.includes(pattern))
}

/**
 * Two silent remounts, then the fallback. That is enough for a page the translator rewrote once,
 * and few enough that a subtree which crashes on every render still settles on the fallback.
 */
const MAX_CONSECUTIVE_REMOUNTS = 2
/** A crash this long after the last remount is a new incident, not the same remount loop. */
const REMOUNT_WINDOW_MS = 5000
/**
 * The `$exception` is captured before this boundary decides what to do with it, so it cannot say
 * whether the scene survived. That is what this event is for. A tab that stays translated can
 * keep triggering the remount all day, and each one is the same fact, so cap the reports.
 */
const MAX_REPORTED_REMOUNTS = 3
let reportedRemounts = 0

/** Asks for the remount from an effect, so the fallback's render stays free of side effects. */
function RemountOnMount({ onRemount }: { onRemount: () => void }): null {
    useEffect(() => {
        onRemount()
    }, [onRemount])
    return null
}

interface RemountRecord {
    count: number
    at: number
}

function canRemountSilently(record: RemountRecord, now: number): boolean {
    return now - record.at > REMOUNT_WINDOW_MS || record.count < MAX_CONSECUTIVE_REMOUNTS
}

interface ErrorBoundaryProps {
    children?: React.ReactNode
    exceptionProps?: Record<string, number | string | boolean | bigint | symbol | null | undefined>
    className?: string
}

export function ErrorBoundary({ children, exceptionProps = {}, className }: ErrorBoundaryProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { openSupportForm } = useActions(supportLogic)
    // PostHogErrorBoundary keeps the caught error in its own state and exposes no reset, so a new
    // key is the only route back to rendering children. Without it the app-root boundary in
    // scenes/App.tsx is terminal: it has no key that ever changes, unlike the per-scene boundary
    // that resets whenever the scene does, so anything thrown from the nav or the command palette
    // leaves a page reload as the only way out.
    const [remountCount, setRemountCount] = useState(0)
    const remounts = useRef<RemountRecord>({ count: 0, at: 0 })

    const remountAfterDOMMutation = useCallback((): void => {
        const now = Date.now()
        const isNewIncident = now - remounts.current.at > REMOUNT_WINDOW_MS
        const count = isNewIncident ? 1 : remounts.current.count + 1
        remounts.current = { count, at: now }
        if (reportedRemounts < MAX_REPORTED_REMOUNTS) {
            reportedRemounts += 1
            posthog.capture('error_boundary_dom_mutation_remounted', { attempt: count })
        }
        setRemountCount((previous) => previous + 1)
    }, [])

    const retryFromFallback = useCallback((): void => {
        remounts.current = { count: 0, at: 0 }
        setRemountCount((previous) => previous + 1)
    }, [])

    const additionalProperties = { ...exceptionProps }

    if (currentTeamId !== undefined) {
        additionalProperties.team_id = currentTeamId
    }

    return (
        <PostHogErrorBoundary
            key={remountCount}
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

                // This error class is transient: the commit that hit a translated text node
                // failed, but a fresh render of the same subtree usually succeeds. So remount the
                // subtree instead of replacing the scene. Translated nodes React thinks it removed
                // can stay on screen, which is a much smaller loss than the whole view.
                if (isPageRewrittenError && canRemountSilently(remounts.current, Date.now())) {
                    return <RemountOnMount onRemount={remountAfterDOMMutation} />
                }

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
                                Page translation stopped PostHog from updating this view, and it kept happening after we
                                reloaded the view for you. This is usually your browser's built-in translation, or an
                                extension that translates the page. Turn translation off for this site, then try again.
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
                            <LemonButton type="primary" center onClick={retryFromFallback} className="flex-1">
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
