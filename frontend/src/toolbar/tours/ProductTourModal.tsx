import { PlusOutlined } from '@ant-design/icons'
import { Button, Col, Input, Modal, Row, Select } from 'antd'
import { useValues } from 'kea'
import React, { useState } from 'react'
import { cohortsModel } from '~/models/cohortsModel'
// import {toursLogic} from "~/toolbar/tours/toursLogic";

export function ProductTourModal(): JSX.Element {
    const [step, setStep] = useState(0)
    // const { tours } = useValues(toursLogic)
    const tour = { steps: [1, 2, 3] }
    const { cohorts } = useValues(cohortsModel)

    return (
        <Modal visible={true}>
            {step === 0 && (
                <>
                    Product tours Improve discoverability by guiding users through a tour of features.
                    <div>
                        No product tours found
                        <Button icon={<PlusOutlined />} onClick={() => setStep(1)}>
                            Create a product tour
                        </Button>
                    </div>
                </>
            )}
            {step !== 0 && (
                <>
                    Create a product tour
                    <Row>
                        <Col>1. Info</Col>
                        <Col>2. Audience</Col>
                        <Col>3. Steps</Col>
                    </Row>
                </>
            )}
            {step === 1 && (
                <div>
                    <Row>
                        Tour name
                        <Input />
                    </Row>
                    <Row>
                        Start point
                        <Input />
                    </Row>
                </div>
            )}
            {step === 2 && (
                <>
                    Audience
                    <Select>
                        {cohorts.map((cohort, i) => (
                            <Select.Option key={i} value={cohort.id}>
                                {cohort.name}
                            </Select.Option>
                        ))}
                    </Select>
                    <Button icon={<PlusOutlined />}>New cohort</Button>
                </>
            )}
            {step === 3 && <>{tour.steps ? <div>blah</div> : <div>blah</div>}</>}
            {step !== 0 && (
                <Button onClick={() => setStep(step + 1)} type="primary">
                    Next
                </Button>
            )}
        </Modal>
    )
}
