import { Button, Input } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CloseOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import React, { useEffect, useState } from 'react'
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
        submit: (result: 'dismissed' | 'partial' | 'completed') => ({ result }),
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
        submit: ({ result }) => {
            // `nps_2106` is used to identify users who have replied to the NPS survey (via cohorts)
            posthog.capture('nps feedback', { ...values.payload, result })
            posthog.people.set({ nps_2106: true })
            actions.setStep(3)
            localStorage.setItem('experimental-nps', 'true')
        },
    }),
})
/* Asks user for NPS-like score feedback (see product-internal#9 for details). To determine if the component should
be shown to a user, we follow these rules:
1. If the user has the appropriate feature flag active (this determines eligibility based on recent 
    activity [e.g. having discovered learnings recently], ...).
2. If the user hasn't filled out the form already (based on local storage). For a persistent store we use the `nps_2016` user property, 
    which excludes a user from the feature flag.
*/
export function NPSPrompt(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { setStep, setPayload, stepBack, submit } = useActions(npsLogic)
    const { step } = useValues(npsLogic)
    const [step2Content, setStep2Content] = useState('')
    const [step3Content, setStep3Content] = useState('')
    // Whether the component should be displayed or not (based on whether it has been filled or not)
    const [hidden, setHidden] = useState(true)

    useEffect(() => {
        if (!localStorage.getItem('experimental-nps')) {
            // Survey hasn't been filled, show component (subject to feature flag below too)
            setTimeout(() => setHidden(false), 10000) // Show after 10s of using the app
        }
    }, [])

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
            submit('partial')
        } else {
            setStep(2)
        }
    }

    const handleStep3 = (): void => {
        setPayload({ feedback_persona: step3Content })
        submit('completed')
        setTimeout(() => setHidden(true), 3500)
    }

    const handleDismiss = (): void => {
        setHidden(true)
        if (step === 0) {
            submit('dismissed')
            return
        }
        setPayload({ feedback_score: step2Content, feedback_persona: step3Content })
        submit('partial')
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
            <div className={`nps-prompt${hidden ? ' hide' : ''}`}>
                <span className="nps-dismiss" onClick={handleDismiss}>
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
                                onKeyDown={(e) => e.key === 'Enter' && e.metaKey && handleStep2()}
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
                                onKeyDown={(e) => e.key === 'Enter' && e.metaKey && handleStep3()}
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
