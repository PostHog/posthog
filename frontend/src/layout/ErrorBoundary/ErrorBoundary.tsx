import './ErrorBoundary.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { PostHogErrorBoundary, type PostHogErrorBoundaryFallbackProps } from 'posthog-js/react'
import posthog from 'posthog-js'
import { teamLogic } from 'scenes/teamLogic'

// Global variable to store the most recent exception event
let globalLastExceptionEvent: any = null
let globalExceptionListener: (() => void) | null = null

// Set up global listener for exception events (only once)
if (!globalExceptionListener && typeof window !== 'undefined') {
    globalExceptionListener = posthog.on('eventCaptured', (event) => {
        if (event.event === '$exception') {
            globalLastExceptionEvent = event
        }
    })
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

                // Use the globally captured exception event
                const exceptionEvent = globalLastExceptionEvent

                // Function to parse exception event data into readable format
                const parseExceptionEvent = (event: any): string => {
                    const uuid = event?.uuid || 'Unknown'
                    const commitSha = event?.properties?.commit_sha || 'Unknown'
                    const feature = event?.properties?.feature || 'Unknown'
                    const exceptionType = event?.properties?.$exception_list?.[0]?.type || 'Unknown'
                    const exceptionValue = event?.properties?.$exception_list?.[0]?.value || 'Unknown'

                    return `UUID: ${uuid}
Commit SHA: ${commitSha}
Feature: ${feature}
Type: ${exceptionType}
Value: ${exceptionValue}`
                }

                return (
                    <div className={clsx('ErrorBoundary', className)}>
                        <h2>An error has occurred</h2>
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
                        Please help us resolve the issue by sending a screenshot of this message.
                        <LemonButton
                            type="primary"
                            fullWidth
                            center
                            onClick={() => {
                                const exceptionData = exceptionEvent ? parseExceptionEvent(exceptionEvent) : undefined
                                openSupportForm({
                                    kind: 'bug',
                                    isEmailFormOpen: true,
                                    message: exceptionData ? `Exception details:\n${exceptionData}\n\n` : '',
                                })
                            }}
                            targetBlank
                            className="mt-2"
                        >
                            Email an engineer
                        </LemonButton>
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
