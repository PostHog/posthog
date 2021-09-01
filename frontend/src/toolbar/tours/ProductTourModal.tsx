import { PlusOutlined } from '@ant-design/icons'
import { Button, Col, Input, Modal, Row, Select } from 'antd'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import React, { useState } from 'react'
import { cohortsModel } from '~/models/cohortsModel'

export function ProductTourModal(): JSX.Element {
    const [step, setStep] = useState(0)
    // const { tour } = useValues(productTourModalLogic)
    const tour = { steps: [1, 2, 3] }
    const { cohorts, cohortsLoading } = useValues(cohortsModel)

    return (
        <Modal
            footer={<div></div>}
            visible={true}
            title={<div style={{ fontSize: 20 }}>{step === 0 ? 'Product tours' : 'Create a product tour'}</div>}
        >
            {step === 0 && (
                <>
                    {/* <PageHeader title="Product tours" /> */}
                    <Row style={{ marginBottom: 16 }}>
                        Improve discoverability by guiding users through a tour of features.
                    </Row>
                    <div
                        style={{
                            backgroundColor: '#fbfbfb',
                            padding: 24,
                            border: '2px solid var(--border)',
                            borderRadius: 10,
                            textAlign: 'center',
                        }}
                    >
                        <Row style={{ paddingBottom: 12, justifyContent: 'center' }}>No product tours found</Row>
                        <Button type="primary" icon={<PlusOutlined />} onClick={() => setStep(1)}>
                            Create a product tour
                        </Button>
                    </div>
                </>
            )}
            {step !== 0 && (
                <>
                    <Row style={{ justifyContent: 'space-evenly', paddingBottom: 16 }}>
                        <div
                            style={{
                                textAlign: 'center',
                                flex: 1,
                                padding: '4px 24px',
                                fontWeight: 600,
                                marginRight: 3,
                                borderRadius: '10px 0px 0px 10px',
                                backgroundColor: 'var(--border)',
                                color: `${step === 1 ? 'black' : '#999999'}`,
                            }}
                        >
                            1. Info
                        </div>
                        <div
                            style={{
                                textAlign: 'center',
                                flex: 1,
                                padding: '4px 24px',
                                fontWeight: 600,
                                marginRight: 3,
                                backgroundColor: 'var(--border)',
                                color: `${step === 2 ? 'black' : '#999999'}`,
                            }}
                        >
                            2. Audience
                        </div>
                        <div
                            style={{
                                textAlign: 'center',
                                flex: 1,
                                padding: '4px 24px',
                                fontWeight: 600,
                                borderRadius: '0px 10px 10px 0px',
                                backgroundColor: 'var(--border',
                                color: `${step === 3 ? 'black' : '#999999'}`,
                            }}
                        >
                            3. Steps
                        </div>
                    </Row>
                </>
            )}
            {step === 1 && (
                <div>
                    <Row>
                        <span style={{ paddingBottom: 4 }}>Tour name</span>
                        <Input placeholder="An internal name to reference this tour. Eg: Onboarding flow" />
                    </Row>
                    <Row>
                        <span style={{ paddingTop: 12, paddingBottom: 4 }}>Start point</span>
                        <Input defaultValue="pie" />
                    </Row>
                </div>
            )}
            {step === 2 && (
                <>
                    Audience
                    <Select>
                        {cohorts.map((cohort) => (
                            <Select.Option value={cohort.id}>{cohort.name}</Select.Option>
                        ))}
                    </Select>
                    <Button icon={<PlusOutlined />}>New cohort</Button>
                </>
            )}
            {step === 3 && <>{tour.steps ? <div></div> : <div></div>}</>}
            {step !== 0 && (
                <Button style={{ float: 'right' }} onClick={() => setStep(step + 1)} type="primary">
                    Next
                </Button>
            )}
        </Modal>
    )
}
