import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheckCircle, IconPullRequest, IconWarning } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { activeCloudRunLogic, CloudRunHandle } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { finishedLocalRunLogic } from 'scenes/onboarding/shared/wizard-sync/finishedLocalRunLogic'
import { currentTaskLabel, pipClass, stepCounts, syncHeadline } from 'scenes/onboarding/shared/wizard-sync/helpers'
import {
    InstallationProgress,
    installationProgressLogic,
    progressFromFinishedLocalRun,
} from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { wizardSyncUiLogic } from 'scenes/onboarding/shared/wizard-sync/wizardSyncUiLogic'

import { ProductKey } from '~/queries/schema/schema-general'

interface QuickstartWizardProgressProps {
    children: (progress: InstallationProgress) => React.ReactNode
    fallback: React.ReactNode
}

function QuickstartCloudProgress({
    activeCloudRun,
    children,
}: {
    activeCloudRun: CloudRunHandle
    children: QuickstartWizardProgressProps['children']
}): JSX.Element {
    const { installationProgress } = useValues(
        installationProgressLogic({
            mode: 'cloud',
            runId: activeCloudRun.runId,
            taskId: activeCloudRun.taskId,
        })
    )

    return <>{children(installationProgress)}</>
}

function QuickstartLocalProgress({ children }: { children: QuickstartWizardProgressProps['children'] }): JSX.Element {
    const { installationProgress } = useValues(installationProgressLogic({ mode: 'local' }))

    return <>{children(installationProgress)}</>
}

function QuickstartLocalProgressDetector({ children, fallback }: QuickstartWizardProgressProps): JSX.Element {
    useMountedLogic(wizardActiveSessionDetectorLogic)
    const { hasActiveSession } = useValues(wizardActiveSessionDetectorLogic)
    const { finishedLocalRun } = useValues(finishedLocalRunLogic)

    if (hasActiveSession) {
        return <QuickstartLocalProgress>{children}</QuickstartLocalProgress>
    }
    if (finishedLocalRun) {
        return <>{children(progressFromFinishedLocalRun(finishedLocalRun))}</>
    }
    return <>{fallback}</>
}

export function QuickstartWizardProgress({ children, fallback }: QuickstartWizardProgressProps): JSX.Element {
    const syncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    const { finishedLocalRun } = useValues(finishedLocalRunLogic)

    if (activeCloudRun) {
        return <QuickstartCloudProgress activeCloudRun={activeCloudRun}>{children}</QuickstartCloudProgress>
    }
    if (syncEnabled) {
        return <QuickstartLocalProgressDetector fallback={fallback}>{children}</QuickstartLocalProgressDetector>
    }
    if (finishedLocalRun) {
        return <>{children(progressFromFinishedLocalRun(finishedLocalRun))}</>
    }
    return <>{fallback}</>
}

// The chip's leading glyph: the page signals live activity with pulsing dots (not spinners),
// so working phases reuse that idiom and terminal phases get a small static icon.
function InstallationStatusDot({ progress }: { progress: InstallationProgress }): JSX.Element {
    if (progress.phase === 'completed') {
        return <IconCheckCircle className="text-sm text-success shrink-0" />
    }
    if (progress.phase === 'error') {
        return <IconWarning className="text-sm text-danger shrink-0" />
    }
    if (progress.prMerged) {
        return <IconPullRequest className="text-sm text-purple shrink-0" />
    }
    return (
        <span className="relative flex items-center justify-center size-2 shrink-0" aria-hidden="true">
            <span className="absolute size-2 rounded-full bg-accent opacity-25 animate-pulse" />
            <span className="relative size-1.5 rounded-full bg-accent" />
        </span>
    )
}

/**
 * Wizard progress as a one-line status chip on its own row below the project token, height-matched
 * to the token chip so the two stack as one quiet family. The whole chip opens the detailed dialog.
 */
export function QuickstartInstallationProgress({ progress }: { progress: InstallationProgress }): JSX.Element {
    const { openDialog } = useActions(wizardSyncUiLogic)
    const task = currentTaskLabel(progress)
    const { completed, total } = stepCounts(progress.steps)

    return (
        <div
            className="basis-full min-w-0"
            role="status"
            aria-live="polite"
            data-attr="quickstart-installation-progress"
        >
            <button
                type="button"
                onClick={openDialog}
                className="group flex w-fit max-w-full min-w-0 cursor-pointer items-center gap-2 rounded border bg-bg-light px-3 py-2 transition-colors hover:bg-fill-highlight-50"
                data-attr="quickstart-installation-status"
            >
                <InstallationStatusDot progress={progress} />
                <span className="text-xs font-medium text-secondary whitespace-nowrap">{syncHeadline(progress)}</span>
                {task && (
                    <span className="min-w-0 max-w-72 truncate text-xs text-tertiary" title={task}>
                        {task}
                    </span>
                )}
                {total > 0 && (
                    <span className="flex shrink-0 items-center gap-2">
                        <span className="flex w-16 items-center gap-0.5">
                            {progress.steps.map((step) => (
                                <span key={step.id} className={cn('h-1 flex-1 rounded-full', pipClass(step.status))} />
                            ))}
                        </span>
                        <span className="text-xs text-tertiary tabular-nums">
                            {completed}/{total}
                        </span>
                    </span>
                )}
                <span className="shrink-0 border-l pl-2 text-xs whitespace-nowrap text-tertiary group-hover:text-primary">
                    View details
                </span>
            </button>
        </div>
    )
}

export function isQuickstartProductInstalling(
    productKey: ProductKey,
    installationProgress?: InstallationProgress
): boolean {
    return (
        productKey === ProductKey.PRODUCT_ANALYTICS &&
        (installationProgress?.phase === 'connecting' || installationProgress?.phase === 'running')
    )
}
