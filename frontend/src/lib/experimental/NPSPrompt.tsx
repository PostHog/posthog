import { Button, Input } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CloseOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import React from 'react'
import './NPSPrompt.scss'
import { npsLogicType } from './NPSPromptType'
import posthog from 'posthog-js'
import nps from './nps.svg'
import { userLogic } from 'scenes/userLogic'
import { dayjs } from 'lib/dayjs'

const NPS_APPEAR_TIMEOUT = 10000
const NPS_HIDE_TIMEOUT = 3500
const NPS_LOCALSTORAGE_KEY = 'experimental-nps-v8'

type Step = 0 | 1 | 2 | 3

interface NPSPayload {
    score?: 1 | 3 | 5 // 1 = not disappointed; 3 = somewhat disappointed; 5 = very disappointed
    feedback_score?: string
    feedback_persona?: string
}

const npsLogic = kea<npsLogicType<NPSPayload, Step>>({
    path: ['lib', 'experimental', 'NPSPrompt'],
    selectors: {
        featureFlagEnabled: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags) => featureFlags[FEATURE_FLAGS.NPS_PROMPT],
        ],
        userIsOldEnough: [
            () => [userLogic.selectors.user],
            (user) => user && dayjs(user.date_joined).isBefore(dayjs().add(-15, 'day')),
        ],
        npsPromptEnabled: [
            (s) => [s.featureFlagEnabled, s.userIsOldEnough],
            (featureFlagEnabled, userIsOldEnough) => featureFlagEnabled && userIsOldEnough,
        ],
    },
    actions: {
        show: true,
        hide: true,
        setStep: (step: Step) => ({ step }),
        stepBack: true,
        setPayload: (payload: NPSPayload | null) => ({ payload }),
        submit: (completed?: boolean) => ({ completed }),
        dismiss: true,
        send: (result: 'completed' | 'partial' | 'dismissed') => ({ result }), // Sends response data to PostHog
    },
    reducers: {
        step: [
            0 as Step,
            {
                setStep: (_, { step }) => step,
                stepBack: (state) => Math.max(state - 1, 0) as Step,
                submit: () => 3,
                // go to step 1 when selecting the score on step 0
                setPayload: (state, { payload }) => (state === 0 && typeof payload?.score !== 'undefined' ? 1 : state),
            },
        ],
        hidden: [true, { show: () => false, hide: () => true }],
        payload: [
            null as NPSPayload | null,
            {
                setPayload: (state, { payload }) => ({ ...state, ...payload }),
            },
        ],
    },
    listeners: ({ values, actions, cache }) => ({
        stepBack: () => {
            if (values.step === 1) {
                actions.setPayload(null)
            }
        },
        dismiss: () => {
            const result = typeof values.payload?.score !== 'undefined' ? 'partial' : 'dismissed'
            actions.hide()
            actions.send(result)
        },
        submit: ({ completed }) => {
            const result = completed ? 'completed' : 'partial'
            actions.send(result)
            cache.timeout = window.setTimeout(() => actions.hide(), NPS_HIDE_TIMEOUT)
        },
        send: ({ result }) => {
            posthog.capture('nps feedback', { ...values.payload, result })

            // `nps_2106` is used to identify users who have replied to the NPS survey (via cohorts)
            posthog.people.set({ nps_2106: true })

            localStorage.setItem(NPS_LOCALSTORAGE_KEY, 'true')
        },
        show: () => {
            posthog.capture('nps modal shown')
        },
    }),
    events: ({ actions, values, cache }) => ({
        afterMount: () => {
            if (values.npsPromptEnabled && !localStorage.getItem(NPS_LOCALSTORAGE_KEY)) {
                cache.timeout = window.setTimeout(() => actions.show(), NPS_APPEAR_TIMEOUT)
            }
        },
        beforeUnmount: () => {
            window.clearTimeout(cache.timeout)
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
    const { setStep, setPayload, stepBack, submit, dismiss } = useActions(npsLogic)
    const { step, payload, hidden, npsPromptEnabled } = useValues(npsLogic)

    if (!npsPromptEnabled) {
        return null
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
                <span className="nps-dismiss" onClick={dismiss}>
                    <CloseOutlined />
                </span>
                <div className="prompt-inner">
                    {step === 0 && (
                        <div data-attr="nps-step-0">
                            <div className="prompt-title">Help us improve PostHog in less than 60 seconds 🙏</div>
                            <div className="question">How would you feel if you could no longer use PostHog?</div>

                            <div className="action-buttons">
                                <Button className="prompt-button" onClick={() => setPayload({ score: 1 })}>
                                    Not disappointed
                                </Button>
                                <Button className="prompt-button" onClick={() => setPayload({ score: 3 })}>
                                    Somewhat disappointed
                                </Button>
                                <Button className="prompt-button" onClick={() => setPayload({ score: 5 })}>
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
                                value={payload?.feedback_score || ''}
                                onChange={(e) => setPayload({ feedback_score: e.target.value })}
                                onKeyDown={(e) => e.key === 'Enter' && e.metaKey && setStep(2)}
                            />
                            <div style={{ textAlign: 'left' }} className="mt">
                                <Button type="link" style={{ paddingLeft: 0 }} onClick={() => submit(false)}>
                                    Finish
                                </Button>
                                <Button style={{ float: 'right' }} onClick={() => setStep(2)}>
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
                                value={payload?.feedback_persona || ''}
                                onChange={(e) => setPayload({ feedback_persona: e.target.value })}
                                onKeyDown={(e) => e.key === 'Enter' && e.metaKey && submit(true)}
                            />
                            <div style={{ textAlign: 'left' }} className="mt">
                                <Button style={{ float: 'right' }} onClick={() => submit(true)}>
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
