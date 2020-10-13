import React, { useState } from 'react'
import { Input, Button, Form, Switch, Slider } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { slugify } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DeleteOutlined, SaveOutlined } from '@ant-design/icons'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'

const editLogic = kea({
    actions: () => ({
        setRolloutPercentage: (rollout_percentage) => ({ rollout_percentage }),
        setFilters: (filters) => ({ filters }),
    }),
    reducers: ({ props }) => ({
        filters: [
            props.featureFlag?.filters ? props.featureFlag.filters : {},
            {
                setFilters: (_, { filters }) => filters,
            },
        ],
        rollout_percentage: [
            props.featureFlag ? props.featureFlag.rollout_percentage : null,
            {
                setRolloutPercentage: (_, { rollout_percentage }) => rollout_percentage,
            },
        ],
    }),
})

function Snippet({ flagKey }) {
    return (
        <CodeSnippet language="javascript" wrap>
            {`if (posthog.isFeatureEnabled('${flagKey ?? ''}')) {
    // activate feature
}`}
        </CodeSnippet>
    )
}

const noop = () => {}

export function EditFeatureFlag({ featureFlag, logic, isNew }) {
    const [form] = Form.useForm()
    const { updateFeatureFlag, createFeatureFlag, deleteFeatureFlag } = useActions(logic)

    const _editLogic = editLogic({ featureFlag })
    const { filters, rollout_percentage } = useValues(_editLogic)
    const { setFilters, setRolloutPercentage } = useActions(_editLogic)
    const [hasKeyChanged, setHasKeyChanged] = useState(false)

    let submitDisabled = rollout_percentage === null && (!filters?.properties || filters.properties.length === 0)

    return (
        <Form
            layout="vertical"
            form={form}
            initialValues={featureFlag}
            onValuesChange={
                !isNew
                    ? (changedValues) => {
                          if (changedValues.key) setHasKeyChanged(changedValues.key !== featureFlag.key)
                      }
                    : noop
            }
            onFinish={(values) => {
                const updatedFlag = { ...featureFlag, ...values, rollout_percentage, filters }
                if (isNew) {
                    createFeatureFlag(updatedFlag)
                } else {
                    updateFeatureFlag(updatedFlag)
                }
            }}
        >
            <Form.Item
                name="name"
                label="Name"
                className={rrwebBlockClass}
                rules={[
                    { required: true, message: 'Please give your feature flag a name, like "experimental feature".' },
                ]}
            >
                <Input
                    autoFocus={isNew}
                    onChange={(e) => form.setFieldsValue({ key: slugify(e.target.value) })}
                    data-attr="feature-flag-name"
                />
            </Form.Item>

            <Form.Item
                name="key"
                label="Key"
                rules={[{ required: true }]}
                validateStatus={!!rollout_percentage && hasKeyChanged ? 'warning' : ''}
                help={
                    !!rollout_percentage && hasKeyChanged ? (
                        <small>
                            Changing this key will
                            <a href="https://posthog.com/docs/features/feature-flags#feature-flag-persistence">
                                {' '}
                                affect the persistence of your flag.
                            </a>
                        </small>
                    ) : (
                        ' '
                    )
                }
            >
                <Input data-attr="feature-flag-key" />
            </Form.Item>

            <Form.Item name="active" label="Feature flag is active" valuePropName="checked">
                <Switch />
            </Form.Item>

            <Form.Item className={rrwebBlockClass} label="Filter by user properties">
                <PropertyFilters
                    pageKey="feature-flag"
                    propertyFilters={filters?.properties}
                    onChange={(properties) => setFilters({ properties })}
                    endpoint="person"
                />
            </Form.Item>

            <Form.Item label="Roll out feature to percentage of users">
                <Switch
                    checked={!!rollout_percentage}
                    onChange={(checked) => (checked ? setRolloutPercentage(30) : setRolloutPercentage(null))}
                    data-attr="feature-flag-switch"
                />
                {rollout_percentage !== null && (
                    <Slider
                        tooltipPlacement="bottom"
                        tipFormatter={(value) => value + '%'}
                        tooltipVisible={true}
                        value={rollout_percentage}
                        onChange={(value) => {
                            setRolloutPercentage(value)
                        }}
                    />
                )}
                <br />
            </Form.Item>

            <Form.Item>
                <Button
                    disabled={submitDisabled}
                    icon={<SaveOutlined />}
                    htmlType="submit"
                    type="primary"
                    data-attr="feature-flag-submit"
                >
                    Save
                </Button>
                {!isNew && (
                    <Button
                        data-attr="delete-flag"
                        className="float-right"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => {
                            deleteFeatureFlag(featureFlag)
                        }}
                    >
                        Delete
                    </Button>
                )}
            </Form.Item>
            <Form.Item shouldUpdate={(prevValues, currentValues) => prevValues.key !== currentValues.key}>
                {({ getFieldValue }) => {
                    return submitDisabled ? (
                        <small>Select either a person property or rollout percentage to save your feature flag.</small>
                    ) : (
                        <span>
                            <br />
                            Example implementation: <Snippet flagKey={getFieldValue('key')} />
                        </span>
                    )
                }}
            </Form.Item>
        </Form>
    )
}
