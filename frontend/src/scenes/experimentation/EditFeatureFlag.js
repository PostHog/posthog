import React, { useState } from 'react'
import { Input, Button, Form, Switch, Slider, Card } from 'antd'
import { kea, useActions, useValues } from 'kea'
import { slugify } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DeleteOutlined, SaveOutlined } from '@ant-design/icons'
import { CodeSnippet } from 'scenes/ingestion/frameworks/CodeSnippet'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { CloseButton } from 'lib/components/CloseButton'

const editLogic = kea({
    actions: () => ({
        setProperties: (index, properties) => ({ index, properties }),
        setRolloutPercentage: (index, rollout_percentage) => ({ index, rollout_percentage }),
        addGroup: true,
        removeGroup: (index) => ({ index }),
    }),
    reducers: ({ props }) => ({
        groups: [
            props.featureFlag?.filters?.groups || [{}],
            {
                setProperties: (state, { index, properties }) => updateAtIndex(state, index, { properties }),
                setRolloutPercentage: (state, { index, rollout_percentage }) =>
                    updateAtIndex(state, index, { rollout_percentage }),
                addGroup: (state) => state.concat([{}]),
                removeGroup: (state, { index }) => {
                    const groups = [...state]
                    groups.splice(index, 1)
                    return groups
                },
            },
        ],
    }),
    selectors: () => ({
        hasRollout: [
            (s) => [s.groups],
            (groups) => groups.filter(({ rollout_percentage }) => rollout_percentage != null).length > 0,
        ],
        hasProperties: [
            (s) => [s.groups],
            (groups) => groups.filter(({ properties }) => properties != null).length > 0,
        ],
    }),
})

function updateAtIndex(state, index, update) {
    const newState = [...state]
    newState[index] = { ...state[index], ...update }
    return newState
}

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
    const { groups, hasRollout, hasProperties } = useValues(_editLogic)
    const { setProperties, setRolloutPercentage, addGroup, removeGroup } = useActions(_editLogic)
    const [hasKeyChanged, setHasKeyChanged] = useState(false)

    const submitDisabled = !hasRollout && !hasProperties

    return (
        <Form
            layout="vertical"
            form={form}
            initialValues={featureFlag}
            onValuesChange={
                !isNew
                    ? (changedValues) => {
                          if (changedValues.key) {
                              setHasKeyChanged(changedValues.key !== featureFlag.key)
                          }
                      }
                    : noop
            }
            onFinish={(values) => {
                const updatedFlag = { ...featureFlag, ...values, filters: { groups } }
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
                validateStatus={!!hasRollout && hasKeyChanged ? 'warning' : ''}
                help={
                    !!hasRollout && hasKeyChanged ? (
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

            {groups.map((group, index) => (
                <Card style={{ position: 'relative', marginBottom: 32 }} key={`${index}-${groups.length}`}>
                    {groups.length !== 1 && (
                        <CloseButton
                            style={{ position: 'absolute', top: 0, right: 0, margin: 4 }}
                            onClick={() => removeGroup(index)}
                        />
                    )}

                    <Form.Item
                        className={rrwebBlockClass}
                        label="Filter by user properties"
                        style={{ position: 'relative' }}
                    >
                        <PropertyFilters
                            pageKey={`feature-flag-${featureFlag.id}-${index}-${groups.length}`}
                            propertyFilters={group?.properties}
                            onChange={(properties) => setProperties(index, properties)}
                            endpoint="person"
                            showConditionBadge
                        />
                    </Form.Item>

                    <Form.Item
                        name="rollout"
                        label="Roll out feature to percentage of users"
                        style={{ marginBottom: 0 }}
                    >
                        <Switch
                            id="rollout"
                            checked={!!group.rollout_percentage}
                            onChange={(checked) =>
                                checked ? setRolloutPercentage(index, 30) : setRolloutPercentage(index, null)
                            }
                            data-attr="feature-flag-switch"
                        />
                        {group.rollout_percentage != null && (
                            <Slider
                                tooltipPlacement="bottom"
                                tipFormatter={(value) => value + '%'}
                                tooltipVisible={true}
                                value={group.rollout_percentage}
                                onChange={(value) => {
                                    setRolloutPercentage(index, value)
                                }}
                            />
                        )}
                        <br />
                    </Form.Item>

                    {index === groups.length - 1 && (
                        <Button style={{ position: 'absolute', marginTop: 8 }} onClick={addGroup}>
                            +
                        </Button>
                    )}
                </Card>
            ))}

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
