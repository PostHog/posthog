import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { activeCloudRunLogic, CloudRunHandle } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { finishedLocalRunLogic } from 'scenes/onboarding/shared/wizard-sync/finishedLocalRunLogic'
import { currentTaskLabel, stepCounts, syncHeadline } from 'scenes/onboarding/shared/wizard-sync/helpers'
import {
    InstallationProgress,
    installationProgressLogic,
    progressFromFinishedLocalRun,
} from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { StatusGlyph } from 'scenes/onboarding/shared/wizard-sync/WizardSyncCard'
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

export function QuickstartInstallationProgress({ progress }: { progress: InstallationProgress }): JSX.Element {
    const { openDialog } = useActions(wizardSyncUiLogic)
    const task = currentTaskLabel(progress)
    const { completed, total } = stepCounts(progress.steps)

    return (
        <div
            className="flex items-center gap-2 rounded border bg-fill-highlight-50 px-2 py-1"
            role="status"
            aria-live="polite"
            data-attr="quickstart-installation-progress"
        >
            <StatusGlyph progress={progress} />
            <div className="flex flex-col min-w-0 leading-tight">
                <span className="text-xs font-semibold">{syncHeadline(progress)}</span>
                <span className="text-xs text-secondary truncate max-w-72" title={task ?? undefined}>
                    {task}
                </span>
            </div>
            {total > 0 && (
                <span className="text-xs text-muted tabular-nums shrink-0">
                    {completed}/{total}
                </span>
            )}
            <LemonButton size="xsmall" onClick={openDialog} data-attr="quickstart-installation-status">
                Details
            </LemonButton>
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
