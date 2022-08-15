import { Button, Col, Divider, Row } from 'antd'
import { useValues } from 'kea'
import React from 'react'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { kafkaInspectorLogic } from './kafkaInspectorLogic'
import { Field, Form } from 'kea-forms'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'

export function KafkaInspectorTab(): JSX.Element {
    const { kafkaMessage } = useValues(kafkaInspectorLogic)

    return (
        <div>
            <h3 className="l3" style={{ marginTop: 16 }}>
                Kafka Inspector
            </h3>
            <div className="mb-4">Debug Kafka messages using the inspector tool.</div>
            <Divider style={{ margin: 0, marginBottom: 16 }} />
            <section>
                <div style={{ display: 'flex', marginBottom: '0.75rem' }}>
                    <Form
                        logic={kafkaInspectorLogic}
                        formKey="fetchKafkaMessage"
                        className="ant-form-horizontal ant-form-hide-required-mark"
                        enableFormOnSubmit
                    >
                        <Row gutter={[24, 24]}>
                            <Col span={8}>
                                <Field name="topic">
                                    <LemonInput placeholder="Topic" />
                                </Field>
                            </Col>
                            <Col span={4}>
                                <Field name="partition">
                                    <LemonInput placeholder="Partition" type="number" />
                                </Field>{' '}
                            </Col>
                            <Col span={4}>
                                <Field name="offset">
                                    <LemonInput placeholder="Offset" type="number" />
                                </Field>{' '}
                            </Col>

                            <Col span={6}>
                                <Button htmlType="submit" type="primary" data-attr="fetch-kafka-message-submit-button">
                                    Fetch message{' '}
                                </Button>
                            </Col>
                        </Row>
                    </Form>
                </div>
            </section>
            <CodeSnippet language={Language.JSON}>
                {kafkaMessage ? JSON.stringify(kafkaMessage, null, 4) : '\n'}
            </CodeSnippet>
        </div>
    )
}
