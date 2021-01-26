import { useActions, useValues } from 'kea'
import React from 'react'
import { hot } from 'react-hot-loader/root'
import { personalizationLogic } from './personalizationLogic'
import { Row, Col } from 'antd'
import { RadioOption } from 'lib/components/RadioOption'
import { ROLES, TEAM_SIZES } from './personalizationData'

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
    const { personalizationData } = useValues(personalizationLogic)
    const { appendPersonalizationData } = useActions(personalizationLogic)

    const handleOptionChanged = (attr: 'role' | 'team_size', value: string | number): void => {
        appendPersonalizationData({ [attr]: value })
    }

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
                <RadioOption
                    options={ROLES}
                    selectedOption={personalizationData?.role}
                    onOptionChanged={(value) => handleOptionChanged('role', value)}
                />
            </div>

            <div style={{ marginTop: 32 }}>
                <div>
                    2. Company's <b>team size</b> is
                </div>
                <RadioOption
                    options={TEAM_SIZES}
                    selectedOption={personalizationData?.team_size}
                    onOptionChanged={(value) => handleOptionChanged('team_size', value)}
                />
            </div>

            {JSON.stringify(personalizationData)}
        </div>
    )
}
