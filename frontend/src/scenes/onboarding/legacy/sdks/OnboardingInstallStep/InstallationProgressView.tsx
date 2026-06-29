import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle, IconX } from '@posthog/icons'
import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { activeCloudRunLogic } from './activeCloudRunLogic'
import { installationProgressLogic, InstallationStep } from './installationProgressLogic'

function StepIcon({ status }: { status: InstallationStep['status'] }): JSX.Element {
    if (status === 'completed') {
        return <IconCheckCircle className="text-success shrink-0" />
    }
    if (status === 'failed') {
        return <IconX className="text-danger shrink-0" />
    }
    if (status === 'in_progress') {
        return <Spinner className="shrink-0" />
    }
    return <span className="w-3.5 h-3.5 rounded-full border border-border shrink-0" />
}

/**
 * Renders the Installation layer's `InstallationProgress` for a cloud run — the merged pipeline
 * stepper plus the terminal payoff (PR link) or failure. Source-agnostic by construction: it only
 * reads `installationProgressLogic`, never the underlying streams.
 */
export function InstallationProgressView({
    runId,
    taskId,
    floating = false,
    onDismiss,
}: {
    runId: string
    taskId: string
    /** Rendered in the floating FAB rather than inline on the install step. */
    floating?: boolean
    onDismiss?: () => void
}): JSX.Element {
    const { installationProgress } = useValues(installationProgressLogic({ mode: 'cloud', runId, taskId }))
    const { setPanelMounted } = useActions(activeCloudRunLogic)
    const { phase, steps, error, prUrl } = installationProgress

    // While shown inline on the install step, hide the floating FAB so the same run isn't in two places.
    useEffect(() => {
        if (floating) {
            return
        }
        setPanelMounted(true)
        return () => setPanelMounted(false)
    }, [floating, setPanelMounted])

    const bannerType = phase === 'completed' ? 'success' : phase === 'error' ? 'error' : 'info'
    const headline =
        phase === 'completed'
            ? 'PostHog is wired up'
            : phase === 'error'
              ? (error?.title ?? 'Installation failed')
              : 'Setting up PostHog…'

    return (
        <LemonBanner type={bannerType} onClose={onDismiss}>
            <div className="flex w-full flex-col gap-2" data-attr="installation-progress">
                <div className="font-semibold">{headline}</div>
                {steps.length > 0 && (
                    <ul className="flex flex-col gap-1.5 m-0 p-0 list-none">
                        {steps.map((step) => (
                            <li key={step.id} className="flex items-center gap-2 text-sm">
                                <StepIcon status={step.status} />
                                <span className={step.status === 'pending' ? 'text-muted' : ''}>{step.label}</span>
                                {step.detail && <span className="text-xs text-muted truncate">— {step.detail}</span>}
                            </li>
                        ))}
                    </ul>
                )}
                {phase === 'error' && error?.detail && <div className="text-sm text-muted">{error.detail}</div>}
                {phase === 'completed' && prUrl && (
                    <Link to={prUrl} target="_blank">
                        Review your pull request
                    </Link>
                )}
                {phase !== 'completed' && phase !== 'error' && (
                    <div className="text-xs text-muted">
                        This runs in the background — keep going and we'll keep this updated.
                    </div>
                )}
            </div>
        </LemonBanner>
    )
}
