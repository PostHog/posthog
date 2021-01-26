import { useValues } from 'kea'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { personalizationLogic } from './personalizationLogic'
import { Row, Col } from 'antd'
import { RadioOption } from 'lib/components/RadioOption'
import { ROLES } from './personalizationData'

export const Personalization = hot(_Personalization)

function _Personalization(): JSX.Element {
    const { step } = useValues(personalizationLogic)
    return (
        <Row style={{ padding: 32 }}>
            <Col xs={24}>{step === 2 && <StepTwo />}</Col>
        </Row>
    )
}

function StepTwo(): JSX.Element {
    return (
        <div>
            <h2 className="subtitle">Great! Just a couple of questions and you're good to go</h2>
            <div>
                You are welcome to skip any question, but filling them out will help us show you features and
                configuration that are more relevant for you.
            </div>

            <div style={{ marginTop: 64 }}>
                <div>
                    1. Your <b>role</b> at company is (or closest to)
                </div>
                <RadioOption options={ROLES} />
            </div>
        </div>
    )
}
