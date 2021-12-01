import { Form, Input } from 'antd'
import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'

export function Experiment(): JSX.Element {
    return (
        <>
            <PageHeader title="New Experiment" />
            <Form name="new-experiment" layout="vertical">
                <Form.Item label="Name" name="name">
                    <Input data-attr="experiment-name" className="ph-ignore-input" />
                </Form.Item>

                <Form.Item label="Description" name="description">
                    <Input.TextArea
                        data-attr="experiment-description"
                        className="ph-ignore-input"
                        placeholder="Adding a helpful description can ensure others know what this experiment is about."
                    />
                </Form.Item>

                <Form.Item label="Feature flag" name="featureflag" />
            </Form>
        </>
    )
}
