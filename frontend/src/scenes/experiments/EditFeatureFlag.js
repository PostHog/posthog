import React from 'react'
import { Input, Button, Form, Switch, Slider } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { slugify } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { CodeSnippet } from 'scenes/onboarding/FrameworkInstructions/CodeSnippet'

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

export function EditFeatureFlag({ featureFlag, logic, isNew }) {
    const [form] = Form.useForm()
    const { updateFeatureFlag, createFeatureFlag } = useActions(logic)

    const _editLogic = editLogic({ featureFlag })
    const { filters, rollout_percentage } = useValues(_editLogic)
    const { setFilters, setRolloutPercentage } = useActions(_editLogic)

    let submitDisabled = rollout_percentage === null && (!filters?.properties || filters.properties.length === 0)
    return (
        <Form
            layout="vertical"
            form={form}
            initialValues={featureFlag}
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

            <Form.Item name="key" label="Key" rules={[{ required: true }]}>
                <Input data-attr="feature-flag-key" />
            </Form.Item>

            <Form.Item name="active" label="Feature flag is active" valuePropName="checked">
                <Switch />
            </Form.Item>

            <Form.Item label="Filter by user properties">
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
                <Button disabled={submitDisabled} htmlType="submit" type="primary" data-attr="feature-flag-submit">
                    Save feature flag
                </Button>
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
