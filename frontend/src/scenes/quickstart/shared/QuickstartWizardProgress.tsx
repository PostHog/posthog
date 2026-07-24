import { useMountedLogic, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { activeCloudRunLogic, CloudRunHandle } from 'scenes/onboarding/shared/wizard-sync/activeCloudRunLogic'
import { finishedLocalRunLogic } from 'scenes/onboarding/shared/wizard-sync/finishedLocalRunLogic'
import {
    InstallationProgress,
    installationProgressLogic,
    progressFromFinishedLocalRun,
} from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'

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

export function isQuickstartProductInstalling(
    productKey: ProductKey,
    installationProgress?: InstallationProgress
): boolean {
    return (
        productKey === ProductKey.PRODUCT_ANALYTICS &&
        (installationProgress?.phase === 'connecting' || installationProgress?.phase === 'running')
    )
}
