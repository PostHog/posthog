import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { cn } from 'lib/utils/css-classes'
import { activeStep, pipClass, syncHeadline, toneTextClass } from 'scenes/onboarding/shared/wizard-sync/helpers'
import { installationProgressLogic } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { StatusGlyph } from 'scenes/onboarding/shared/wizard-sync/WizardSyncCard'
import { wizardSyncUiLogic } from 'scenes/onboarding/shared/wizard-sync/wizardSyncUiLogic'

/**
 * Rail-sized summary of a live wizard run: glyph + headline, the step it is on, and the pip strip.
 * A miniature of the detached widget's collapsed card, restyled to sit among the setup widgets.
 */
function InstallationCard({ workflowId }: { workflowId: string }): JSX.Element {
    const { installationProgress } = useValues(installationProgressLogic({ mode: 'local', workflowId }))
    const { claimInlinePanel, releaseInlinePanel } = useActions(wizardSyncUiLogic)

    // This card is the run's surface while the rail shows it, so the detached widget stands down.
    useEffect(() => {
        claimInlinePanel()
        return () => releaseInlinePanel()
    }, [claimInlinePanel, releaseInlinePanel])

    const step = activeStep(installationProgress.steps)
    return (
        <div className="flex flex-col gap-1.5 rounded border border-primary bg-surface-primary px-2.5 py-2">
            <div className="flex items-center gap-2 min-w-0">
                <span className="shrink-0 [&_svg]:size-4 [&_.Spinner]:text-base">
                    <StatusGlyph progress={installationProgress} />
                </span>
                <span className={cn('text-[13px] font-medium truncate', toneTextClass(installationProgress))}>
                    {syncHeadline(installationProgress)}
                </span>
            </div>
            {step && <p className="m-0 text-xs text-secondary truncate">{step.detail ?? step.label}</p>}
            {installationProgress.steps.length > 0 && (
                <div className="flex items-center gap-1">
                    {installationProgress.steps.map((s) => (
                        <span key={s.id} className={cn('h-1 flex-1 rounded-full', pipClass(s.status))} />
                    ))}
                </div>
            )}
        </div>
    )
}

/**
 * The "Installation" block of the inbox setup column, present only while a wizard run is in flight.
 * Renders its own section wrapper so the heading disappears with the run.
 */
export function InstallationSetupSection(): JSX.Element | null {
    // The detector's cheap poll is what tells us a run exists at all; mounting it here means the
    // rail doesn't depend on the FAB being rendered to find the run.
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { shouldStream, activeWorkflowId } = useValues(wizardActiveSessionDetectorLogic)

    if (!shouldStream || !activeWorkflowId) {
        return null
    }

    return (
        <div className="flex flex-col">
            <h4 className="text-sm font-medium text-tertiary mt-0 mb-3.5">Installation</h4>
            <div className="flex flex-col gap-1.5">
                <InstallationCard workflowId={activeWorkflowId} />
            </div>
        </div>
    )
}
