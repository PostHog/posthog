import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React from 'react'
import { BOOKMARKLET } from '../constants'
import { ingestionLogic } from '../ingestionLogic'
import './Panels.scss'
import { ArrowLeftOutlined } from '@ant-design/icons'

export function PanelFooter(): JSX.Element {
    const { platform } = useValues(ingestionLogic)
    const { setPlatform, setVerify } = useActions(ingestionLogic)
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
                            setVerify(true)
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
                        onClick={() => setVerify(true)}
                    >
                        Continue
                    </LemonButton>
                    <LemonButton
                        className="mt-2"
                        size="large"
                        fullWidth
                        center
                        type="secondary"
                        onClick={() => setVerify(true)}
                    >
                        Skip for now
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function PanelHeader(): JSX.Element | null {
    const { isSmallScreen, previousStepName, index } = useValues(ingestionLogic)
    const { onBack } = useActions(ingestionLogic)

    // no back buttons on the first screen
    if (index === 0) {
        return null
    }

    return (
        <div className="flex items-center" data-attr="wizard-step-counter">
            <LemonButton type="tertiary" status="primary" onClick={onBack} icon={<ArrowLeftOutlined />}>
                {isSmallScreen ? '' : previousStepName}
            </LemonButton>
        </div>
    )
}
