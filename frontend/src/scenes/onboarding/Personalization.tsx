import { useActions, useValues } from 'kea'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { personalizationLogic } from './personalizationLogic'
import { Row, Col, Button } from 'antd'
import { RadioSelect } from 'lib/components/RadioSelect'
import { ROLES, TEAM_SIZES } from './personalizationOptions'
import { Link } from 'lib/components/Link'
import './Personalization.scss'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { router } from 'kea-router'

export const Personalization = hot(_Personalization)

function _Personalization(): JSX.Element {
    const { step } = useValues(personalizationLogic)

    // TODO: Redirect if personalization has been completed

    return (
        <Row className="personalization-screen">
            <Col xs={24}>{step === null && <StepOne />}</Col>
            <Col xs={24}>{step === 2 && <StepTwo />}</Col>
        </Row>
    )
}

function StepOne(): JSX.Element {
    const { push } = useActions(router)
    return (
        <div>
            <h2 className="subtitle">Nothing to see here yet! Tap Continue</h2>
            <Button type="primary" onClick={() => push('/personalization?step=2')}>
                Continue
            </Button>
        </div>
    )
}

function StepTwo(): JSX.Element {
    const { personalizationData, step } = useValues(personalizationLogic)
    const { appendPersonalizationData } = useActions(personalizationLogic)
    const { reportPersonalizationSkipped, reportPersonalization } = useActions(eventUsageLogic)

    const handleOptionChanged = (attr: 'role' | 'team_size', value: string | null): void => {
        appendPersonalizationData({ [attr]: value })
    }

    const handleContinue = (): void => {
        reportPersonalization(personalizationData, step, answeredQuestionCount === TOTAL_QUESTION_COUNT)
        // TODO: Update organization record
        // :TODO: Is there a way to force default insights graph this without hard reload?
        location.href = '/'
    }

    const answeredQuestionCount: number = personalizationData
        ? (!!personalizationData.role ? 1 : 0) + (!!personalizationData.team_size ? 1 : 0)
        : 0
    const TOTAL_QUESTION_COUNT = 2

    return (
        <div>
            <h2 className="subtitle">Great! Just a couple of questions and you're good to go</h2>
            <div>
                You are welcome to skip any question, but filling them out will help us show you features and
                configuration that are more relevant for you.
            </div>

            <div style={{ marginTop: 32 }}>
                <div>
                    1. <b>Your role</b> at company is (or closest to)
                </div>
                <RadioSelect
                    options={ROLES}
                    selectedOption={personalizationData.role}
                    onOptionChanged={(value) => handleOptionChanged('role', value)}
                />
            </div>

            <div style={{ marginTop: 32 }}>
                <div>
                    2. Company's <b>team size</b> is
                </div>
                <RadioSelect
                    options={TEAM_SIZES}
                    selectedOption={personalizationData.team_size}
                    onOptionChanged={(value) => handleOptionChanged('team_size', value)}
                />
            </div>

            <div className="section-continue">
                {answeredQuestionCount === 0 ? (
                    <Link to="/" onClick={() => reportPersonalizationSkipped(step)}>
                        Skip personalization
                    </Link>
                ) : (
                    <Button
                        type={answeredQuestionCount === TOTAL_QUESTION_COUNT ? 'primary' : 'default'}
                        onClick={handleContinue}
                    >
                        Continue
                    </Button>
                )}
            </div>
        </div>
    )
}
