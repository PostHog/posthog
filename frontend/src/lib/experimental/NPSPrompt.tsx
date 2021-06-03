import { Button, Input } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CloseOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import React from 'react'
import './NPSPrompt.scss'
import { npsLogicType } from './NPSPromptType'

interface NPSPayload {
    score: 1 | 3 | 5 // 1 = not disappointed; 3 = somewhat disappointed; 5 = very disappointed
    feedback_persona?: string
    feedback_benefits?: string
}

const npsLogic = kea<npsLogicType<NPSPayload>>({
    actions: {
        setStep: (step: number) => ({ step }),
        setPayload: (payload: NPSPayload | null, merge: boolean = true) => ({ payload, merge }),
        stepBack: true,
    },
    reducers: {
        step: [0, { setStep: (_, { step }) => step }],
        payload: [
            null as NPSPayload | null,
            {
                setPayload: (state, { payload, merge }) => (merge && state ? { ...state, ...payload } : payload),
            },
        ],
    },
    listeners: ({ values, actions }) => ({
        stepBack: () => {
            actions.setStep(values.step - 1)
            if (values.step === 1) {
                actions.setPayload(null)
            }
        },
    }),
})

export function NPSPrompt(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { setStep, setPayload, stepBack } = useActions(npsLogic)
    const { step } = useValues(npsLogic)

    if (!featureFlags[FEATURE_FLAGS.NPS_PROMPT]) {
        return null
    }

    const handleScoreSelect = (score: 1 | 3 | 5): void => {
        setPayload({ score })
        setStep(1)
    }

    const Header = (
        <div className="nps-header">
            <div className="cursor-pointer" onClick={stepBack}>
                <ArrowLeftOutlined />
            </div>
            <div className="nps-progress">
                {[0, 1, 2].map((val) => (
                    <div className={`pg-item${val >= step ? ' completed' : ''}`} key={val} />
                ))}
            </div>
        </div>
    )

    return (
        <>
            <div className="nps-prompt">
                <span className="nps-dismiss">
                    <CloseOutlined />
                </span>
                <div className="prompt-inner">
                    {step === 0 && (
                        <div data-attr="nps-step-0">
                            <div className="prompt-title">Help us improve PostHog in less than 60 seconds 🙏</div>
                            <div className="question">How would you feel if you could no longer use PostHog?</div>

                            <div className="action-buttons">
                                <Button className="prompt-button" onClick={() => handleScoreSelect(1)}>
                                    Not disappointed
                                </Button>
                                <Button className="prompt-button" onClick={() => handleScoreSelect(3)}>
                                    Somewhat disappointed
                                </Button>
                                <Button className="prompt-button" onClick={() => handleScoreSelect(5)}>
                                    Very disappointed
                                </Button>
                            </div>
                        </div>
                    )}
                    {step === 1 && (
                        <div data-attr="nps-step-1">
                            {Header}
                            <div className="question">
                                What type of person or company could benefit most from PostHog?
                            </div>
                            <Input.TextArea autoFocus />
                        </div>
                    )}
                </div>
            </div>
        </>
    )
}
