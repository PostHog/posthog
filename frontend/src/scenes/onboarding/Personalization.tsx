import { useActions, useValues } from 'kea'
import React from 'react'
import { personalizationLogic } from './personalizationLogic'
import { Row, Col, Button } from 'antd'
import { RadioSelect } from 'lib/components/RadioSelect'
import { ROLES, PRODUCTS, IS_TECHNICAL } from './personalizationOptions'
import { Link } from 'lib/components/Link'
import './Personalization.scss'

export function Personalization(): JSX.Element {
    const { personalizationData } = useValues(personalizationLogic)
    const { appendPersonalizationData, reportPersonalizationSkipped, reportPersonalization } =
        useActions(personalizationLogic)

    const handleContinue = (): void => {
        reportPersonalization(personalizationData, answeredQuestionCount === TOTAL_QUESTION_COUNT)
    }

    const answeredQuestionCount: number = personalizationData
        ? (!!personalizationData.role ? 1 : 0) +
          (!!personalizationData.products && personalizationData.products.length ? 1 : 0) +
          (!!personalizationData.technical ? 1 : 0)
        : 0
    const TOTAL_QUESTION_COUNT = 3

    const askTechnicalQuestion = !!personalizationData.role && personalizationData.role !== 'engineer' // Ask the user if they are technical?

    return (
        <Row className="personalization-screen">
            <Col xs={24}>
                <div style={{ marginBottom: 64 }}>
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
                            identifier="personalization-role"
                            options={ROLES}
                            selectedOption={personalizationData.role}
                            onOptionChanged={(value) => {
                                if (value === 'engineer') {
                                    // If user is an engineer, we assume technical by default
                                    appendPersonalizationData('technical', 'technical')
                                } else {
                                    appendPersonalizationData('technical', null)
                                }
                                appendPersonalizationData('role', value)
                            }}
                        />
                    </div>
                    <div style={{ marginTop: 32 }} className={`toggle-question${askTechnicalQuestion ? ' show' : ''}`}>
                        <div>
                            2. Are you <b>technical</b>? (i.e. coding/developer expertise)
                        </div>
                        <RadioSelect
                            identifier="personalization-technical"
                            options={IS_TECHNICAL}
                            selectedOption={personalizationData.technical}
                            onOptionChanged={(value) => appendPersonalizationData('technical', value)}
                        />
                    </div>

                    <div style={{ marginTop: 32 }}>
                        <div>
                            {askTechnicalQuestion ? '3' : '2'}. What <b>products</b> does your company/team have? Select{' '}
                            <b>all</b> that apply
                        </div>

                        <RadioSelect
                            identifier="personalization-products"
                            options={PRODUCTS}
                            selectedOption={personalizationData.products}
                            onOptionChanged={(value) => appendPersonalizationData('products', value)}
                            multipleSelection
                        />
                        <div
                            className={`multiselect-reminder${
                                personalizationData.products && personalizationData.products.length === 1 ? ' show' : ''
                            }`}
                        >
                            Any other product? Remember to <b>select all that apply</b>
                        </div>
                    </div>

                    <div className="section-continue">
                        {answeredQuestionCount === 0 ? (
                            <Link to="/" onClick={() => reportPersonalizationSkipped()}>
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
            </Col>
        </Row>
    )
}
