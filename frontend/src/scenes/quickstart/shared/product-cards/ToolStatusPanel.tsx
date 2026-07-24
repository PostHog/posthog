import { useActions } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { currentTaskLabel } from 'scenes/onboarding/shared/wizard-sync/helpers'
import { InstallationProgress } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { QuickstartToolStatus, quickstartLogic } from '../../quickstartLogic'
import { captureQuickstartAction } from '../captureQuickstartAction'
import { isQuickstartProductInstalling } from '../QuickstartWizardProgress'
import { JourneyMeter } from './JourneyMeter'

/** Activity evidence and the best available improvement, without implying a finite completion goal. */
export function ToolStatusPanel({
    status,
    productKey,
    installationProgress,
}: {
    status: QuickstartToolStatus
    productKey: ProductKey
    installationProgress?: InstallationProgress
}): JSX.Element {
    const { openTaskGuidance } = useActions(quickstartLogic)
    const nextStep = status.nextStep
    const installationInProgress = isQuickstartProductInstalling(productKey, installationProgress)

    return (
        <div className="flex flex-col gap-2 border-t pt-3">
            <JourneyMeter status={status} productKey={productKey} />
            <div className="min-h-11 text-xs">
                {installationInProgress && installationProgress ? (
                    <>
                        <div className="font-medium text-secondary mb-0.5">Setup in progress</div>
                        <div className="font-medium text-accent line-clamp-2" data-attr="quickstart-current-task">
                            {currentTaskLabel(installationProgress)}
                        </div>
                    </>
                ) : (
                    nextStep && (
                        <>
                            <div className="font-medium text-secondary mb-0.5">Next improvement</div>
                            <Link
                                onClick={() => {
                                    captureQuickstartAction('open_recommended_task', productKey, {
                                        step_key: nextStep.key,
                                    })
                                    openTaskGuidance(productKey, nextStep.key)
                                }}
                                className="font-medium text-accent whitespace-normal text-left line-clamp-2"
                                data-attr={`quickstart-recommended-task-${productKey}`}
                            >
                                {nextStep.label}
                            </Link>
                        </>
                    )
                )}
            </div>
        </div>
    )
}
