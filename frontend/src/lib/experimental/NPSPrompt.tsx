import { Button, Input } from 'antd'
import { useActions, useValues } from 'kea'
import { CloseOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import React from 'react'
import './NPSPrompt.scss'
import nps from './nps.svg'
import { npsLogic } from 'lib/experimental/npsLogic'

/* Asks user for NPS-like score feedback (see product-internal#9 for details). To determine if the component should
be shown to a user, we follow these rules:
1. If the user has the appropriate feature flag active (this determines eligibility based on recent 
    activity [e.g. having discovered learnings recently], ...).
2. If the user hasn't filled out the form already (based on local storage). For a persistent store we use the `nps_2016` user property, 
    which excludes a user from the feature flag.
*/
export function NPSPrompt(): JSX.Element | null {
    const { setStep, setPayload, stepBack, submit } = useActions(npsLogic)
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
                <span className="nps-dismiss" onClick={submit}>
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
                                <Button type="link" style={{ paddingLeft: 0 }} onClick={() => submit()}>
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
                                onKeyDown={(e) => e.key === 'Enter' && e.metaKey && submit()}
                            />
                            <div style={{ textAlign: 'left' }} className="mt">
                                <Button style={{ float: 'right' }} onClick={submit}>
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
