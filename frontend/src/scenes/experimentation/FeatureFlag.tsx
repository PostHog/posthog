import React from 'react'
import { Input, Button, Form, Switch, Slider, Card } from 'antd'
import { useValues } from 'kea'
import { SceneLoading, slugify } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DeleteOutlined, SaveOutlined } from '@ant-design/icons'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { CloseButton } from 'lib/components/CloseButton'
import { featureFlagLogic } from './featureFlagLogic'
import { featureFlagsLogic } from './featureFlagsLogic'

function Snippet({ key }: { key: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`if (posthog.isFeatureEnabled('${key ?? ''}')) {
    // run your activation code here
}`}
        </CodeSnippet>
    )
}

const noop = (): void => {}

export function FeatureFlag(): JSX.Element {
    const [form] = Form.useForm()
    const { openedFeatureFlagId } = useValues(featureFlagsLogic)
    const logic = featureFlagLogic({ featureFlagId: openedFeatureFlagId })
    const { featureFlag } = useValues(logic)
    const isNew = true // TODO
    const groups = [] // TODO
    const submitDisabled = false // TODO
    const hasRollout = false

    /*const { updateFeatureFlag, createFeatureFlag, deleteFeatureFlag } = useActions(logic)

    const { groups, hasRollout, hasProperties } = useValues(_editLogic)
    const { setProperties, setRolloutPercentage, addGroup, removeGroup } = useActions(_editLogic)
    const [hasKeyChanged, setHasKeyChanged] = useState(false)

    const submitDisabled = !hasRollout && !hasProperties*/

    return (
        <>
            {featureFlag ? (
                <Form
                    layout="vertical"
                    form={form}
                    initialValues={{ name: featureFlag.name, key: featureFlag.key, active: featureFlag.active }}
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
                        <Input data-attr="feature-flag-key" className="ph-ignore-input" />
                    </Form.Item>

                    <Form.Item
                        name="name"
                        label="Name"
                        rules={[
                            {
                                required: true,
                                message: 'Please give your feature flag a name, like "experimental feature".',
                            },
                        ]}
                    >
                        <Input
                            className="ph-ignore-input"
                            autoFocus={isNew}
                            onChange={(e) => form.setFieldsValue({ key: slugify(e.target.value) })}
                            data-attr="feature-flag-name"
                        />
                    </Form.Item>

                    <Form.Item name="active" label="Feature flag is active" valuePropName="checked">
                        <Switch />
                    </Form.Item>

                    {featureFlag.filters.groups.map((group, index) => (
                        <Card style={{ position: 'relative', marginBottom: 32 }} key={`${index}-${groups.length}`}>
                            {groups.length !== 1 && (
                                <CloseButton
                                    style={{ position: 'absolute', top: 0, right: 0, margin: 4 }}
                                    onClick={() => removeGroup(index)}
                                />
                            )}

                            <Form.Item label="Filter by user properties" style={{ position: 'relative' }}>
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
                                <small>
                                    Select either a person property or rollout percentage to save your feature flag.
                                </small>
                            ) : (
                                <span>
                                    <br />
                                    Example implementation: <Snippet key={getFieldValue('key')} />
                                </span>
                            )
                        }}
                    </Form.Item>
                </Form>
            ) : (
                <SceneLoading />
            )}
        </>
    )
}
