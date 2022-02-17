import { Card, Col, Row } from 'antd'
import { IconCheckmark, IconRadioButtonUnchecked } from 'lib/components/icons'
import React, { useState } from 'react'
import './Experiment.scss'

export function ExperimentWorkflow(): JSX.Element {
    const [workflowValidateStepCompleted, setWorkflowValidateStepCompleted] = useState(false)
    const [workflowLaunchStepCompleted, setWorkflowLaunchStepCompleted] = useState(false)

    return (
        <Card className="experiment-workflow" title={<span className="card-secondary">Experiment workflow</span>}>
            <Row>
                <Col className="exp-workflow-step step-completed full-width">
                    <Row align="middle">
                        {true ? (
                            <IconCheckmark style={{ color: 'var(--primary)', fontSize: 24 }} />
                        ) : (
                            <IconRadioButtonUnchecked />
                        )}
                        <b className="ml-05">Create experiment</b>
                    </Row>
                    <div className="ml-2">Set variants, select participants, and add secondary metrics</div>
                </Col>
            </Row>
            <Row>
                <Col
                    className={`full-width exp-workflow-step ${workflowValidateStepCompleted ? 'step-completed' : ''}`}
                    onClick={() => setWorkflowValidateStepCompleted(!workflowValidateStepCompleted)}
                >
                    <Row align="middle">
                        {workflowValidateStepCompleted ? (
                            <IconCheckmark style={{ color: 'var(--primary)', fontSize: 24 }} />
                        ) : (
                            <IconRadioButtonUnchecked />
                        )}
                        <b className="ml-05">Validate experiment</b>
                    </Row>
                    <div className="ml-2">
                        Once you've written your code, it's a good idea to test that each variant behaves as you'd
                        expect.
                    </div>
                </Col>
            </Row>
            <Row>
                <Col
                    className={`full-width exp-workflow-step ${workflowLaunchStepCompleted ? 'step-completed' : ''}`}
                    onClick={() => setWorkflowLaunchStepCompleted(!workflowLaunchStepCompleted)}
                >
                    <Row align="middle">
                        {workflowLaunchStepCompleted ? (
                            <IconCheckmark style={{ color: 'var(--primary)', fontSize: 24 }} />
                        ) : (
                            <IconRadioButtonUnchecked />
                        )}
                        <b className="ml-05">Launch experiment</b>
                    </Row>
                    <div className="ml-2">
                        Run your experiment, monitor results, and decide when to terminate your experiment.
                    </div>
                </Col>
            </Row>
        </Card>
    )
}
