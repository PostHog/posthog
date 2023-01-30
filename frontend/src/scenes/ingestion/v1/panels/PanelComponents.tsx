import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { BOOKMARKLET } from '../constants'
import { ingestionLogic, INGESTION_STEPS } from '../ingestionLogic'
import './Panels.scss'
import { IconArrowLeft } from 'lib/lemon-ui/icons'

export function PanelFooterToRecordingStep(): JSX.Element {
    const { platform } = useValues(ingestionLogic)
    const { setPlatform, setRecording } = useActions(ingestionLogic)
    const { reportIngestionTryWithBookmarkletClicked } = useActions(eventUsageLogic)

    return (
        <div className="panel-footer">
            <LemonDivider thick dashed className="my-6" />
            {platform === BOOKMARKLET ? (
                <div>
                    <LemonButton
                        type="primary"
                        size="large"
                        fullWidth
                        center
                        onClick={() => {
                            reportIngestionTryWithBookmarkletClicked()
                            setRecording(true)
                        }}
                    >
                        Try PostHog with the exploration bookmarklet
                    </LemonButton>
                    <LemonButton
                        className="mt-2"
                        size="large"
                        fullWidth
                        center
                        type="secondary"
                        onClick={() => setPlatform(null)}
                    >
                        Back to setup
                    </LemonButton>
                </div>
            ) : (
                <div>
                    <LemonButton
                        type="primary"
                        size="large"
                        fullWidth
                        center
                        className="mb-2"
                        onClick={() => setRecording(true)}
                    >
                        Continue
                    </LemonButton>
                    <LemonButton
                        className="mt-2"
                        size="large"
                        fullWidth
                        center
                        type="secondary"
                        onClick={() => setRecording(true)}
                    >
                        Skip for now
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function PanelHeader(): JSX.Element | null {
    const { isSmallScreen, previousStep, currentStep } = useValues(ingestionLogic)
    const { onBack } = useActions(ingestionLogic)

    // no back buttons on the first screen
    if (currentStep === INGESTION_STEPS.START) {
        return null
    }

    return (
        <div className="flex items-center mb-2" data-attr="wizard-step-counter">
            <LemonButton type="tertiary" status="primary" onClick={onBack} icon={<IconArrowLeft />} size="small">
                {isSmallScreen ? '' : previousStep}
            </LemonButton>
        </div>
    )
}
