import { Button } from 'antd'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import React from 'react'
import './NPSPrompt.scss'

export function NPSPrompt(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.NPS_PROMPT]) {
        return null
    }

    return (
        <>
            <div className="nps-prompt">
                <div className="prompt-inner">
                    <div className="prompt-title">Help us improve PostHog in less than 60 seconds 🙏</div>
                    <div className="question">How would you feel if you could no longer use PostHog?</div>

                    <div className="action-buttons">
                        <Button className="prompt-button">Not disappointed</Button>
                        <Button className="prompt-button">Somewhat disappointed</Button>{' '}
                        <Button className="prompt-button">Very disappointed</Button>{' '}
                    </div>
                </div>
            </div>
        </>
    )
}
