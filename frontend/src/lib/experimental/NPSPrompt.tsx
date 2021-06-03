import { Button, Input } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CloseOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import React, { useState } from 'react'
import './NPSPrompt.scss'
import { npsLogicType } from './NPSPromptType'
import posthog from 'posthog-js'
import nps from './nps.svg'

interface NPSPayload {
    score?: 1 | 3 | 5 // 1 = not disappointed; 3 = somewhat disappointed; 5 = very disappointed
    feedback_score?: string
    feedback_persona?: string
}

const npsLogic = kea<npsLogicType<NPSPayload>>({
    actions: {
        setStep: (step: number) => ({ step }),
        setPayload: (payload: NPSPayload | null, merge: boolean = true) => ({ payload, merge }),
        stepBack: true,
        submit: true,
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
        submit: () => {
            if (!values.payload) {
                return
            }
            posthog.capture('nps feedback', values.payload)
            actions.setStep(3)
        },
    }),
})

export function NPSPrompt(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { setStep, setPayload, stepBack, submit } = useActions(npsLogic)
    const { step } = useValues(npsLogic)
    const [step2Content, setStep2Content] = useState('')
    const [step3Content, setStep3Content] = useState('')

    if (!featureFlags[FEATURE_FLAGS.NPS_PROMPT]) {
        return null
    }

    const handleStep1 = (score: 1 | 3 | 5): void => {
        setPayload({ score })
        setStep(1)
    }

    const handleStep2 = (sendSubmission: boolean = false): void => {
        setPayload({ feedback_score: step2Content })
        if (sendSubmission) {
            // TODO
        } else {
            setStep(2)
        }
    }

    const handleStep3 = (): void => {
        setPayload({ feedback_persona: step3Content })
        submit()
    }

    const Header = (
        <div className="nps-header">
            <div className="cursor-pointer" onClick={stepBack}>
                <ArrowLeftOutlined />
            </div>
            <div className="nps-progress">
                {[0, 1, 2].map((val) => (
                    <div className={`pg-item${val <= step ? ' completed' : ''}`} key={val} />
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
                                <Button className="prompt-button" onClick={() => handleStep1(1)}>
                                    Not disappointed
                                </Button>
                                <Button className="prompt-button" onClick={() => handleStep1(3)}>
                                    Somewhat disappointed
                                </Button>
                                <Button className="prompt-button" onClick={() => handleStep1(5)}>
                                    Very disappointed
                                </Button>
                            </div>
                        </div>
                    )}
                    {step === 1 && (
                        <div data-attr="nps-step-1">
                            {Header}
                            <div className="question">What's the main reason behind this score?</div>
                            <Input.TextArea
                                autoFocus
                                placeholder="You can describe the key benefits you get from PostHog, shortcomings or anything else..."
                                value={step2Content}
                                onChange={(e) => setStep2Content(e.target.value)}
                            />
                            <div style={{ textAlign: 'left' }} className="mt">
                                <Button type="link" style={{ paddingLeft: 0 }} onClick={() => handleStep2(true)}>
                                    Finish
                                </Button>
                                <Button style={{ float: 'right' }} onClick={() => handleStep2()}>
                                    Continue
                                </Button>
                            </div>
                        </div>
                    )}
                    {step === 2 && (
                        <div data-attr="nps-step-2">
                            {Header}
                            <div className="question">
                                Last one. What type of person or company do you think could benefit most from PostHog?
                            </div>
                            <Input.TextArea
                                autoFocus
                                placeholder="You can describe their role, background, company or team size, ..."
                                value={step3Content}
                                onChange={(e) => setStep3Content(e.target.value)}
                            />
                            <div style={{ textAlign: 'left' }} className="mt">
                                <Button style={{ float: 'right' }} onClick={handleStep3}>
                                    Finish
                                </Button>
                            </div>
                        </div>
                    )}
                    {step === 3 && (
                        <div data-attr="nps-step-2" style={{ display: 'flex', alignItems: 'center' }}>
                            <img src={nps} alt="" height={40} />
                            <div className="prompt-title" style={{ margin: 0 }}>
                                Thanks for helping us improve PostHog!
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </>
    )
}
