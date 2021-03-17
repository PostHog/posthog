import React from 'react'
import { Input, Button, Form, Switch, Slider, Card, Row, Col, Collapse } from 'antd'
import { useActions, useValues } from 'kea'
import { SceneLoading } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DeleteOutlined, SaveOutlined } from '@ant-design/icons'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { CloseButton } from 'lib/components/CloseButton'
import { featureFlagLogic } from './featureFlagLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilter } from '~/types'

function Snippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`if (posthog.isFeatureEnabled('${flagKey ?? ''}')) {
    // run your activation code here
}`}
        </CodeSnippet>
    )
}

const noop = (): void => {}

export function FeatureFlag(): JSX.Element {
    const [form] = Form.useForm()
    const { featureFlag, featureFlagId } = useValues(featureFlagLogic)
    const { addMatchGroup, updateMatchGroup, removeMatchGroup } = useActions(featureFlagLogic)
    const isNew = true // TODO
    const submitDisabled = false // TODO
    const hasRollout = false
    const groups = []

    /*const { updateFeatureFlag, createFeatureFlag, deleteFeatureFlag } = useActions(logic)

    const { groups, hasRollout, hasProperties } = useValues(_editLogic)
    const { setProperties, setRolloutPercentage, addGroup, removeGroup } = useActions(_editLogic)
    const [hasKeyChanged, setHasKeyChanged] = useState(false)

    const submitDisabled = !hasRollout && !hasProperties*/

    return (
        <>
            <PageHeader
                title="Feature Flag"
                buttons={
                    <div>
                        {featureFlagId !== 'new' && (
                            <Button
                                data-attr="delete-flag"
                                danger
                                icon={<DeleteOutlined />}
                                onClick={() => {
                                    deleteFeatureFlag(featureFlag)
                                }}
                                style={{ marginRight: 16 }}
                            >
                                Delete
                            </Button>
                        )}
                        <Button
                            disabled={submitDisabled}
                            icon={<SaveOutlined />}
                            type="primary"
                            data-attr="feature-flag-submit"
                        >
                            Save changes
                        </Button>
                    </div>
                }
            />
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
                        console.log(values)
                        const updatedFlag = { ...featureFlag, ...values, filters: { groups } }
                        if (isNew) {
                            createFeatureFlag(updatedFlag)
                        } else {
                            updateFeatureFlag(updatedFlag)
                        }
                    }}
                    requiredMark={false}
                >
                    <Row gutter={16} style={{ marginTop: 32 }}>
                        <Col span={24} md={12}>
                            <h3 className="l3">General configuration</h3>
                            <div className="text-muted mb">
                                General settings for your feature flag and integration instructions.
                            </div>
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
                                <Input data-attr="feature-flag-key" className="ph-ignore-input" autoFocus />
                            </Form.Item>

                            <Form.Item name="name" label="Description">
                                <Input.TextArea className="ph-ignore-input" data-attr="feature-flag-description" />
                            </Form.Item>

                            <Form.Item name="active" label="Feature flag is active" valuePropName="checked">
                                <Switch />
                            </Form.Item>

                            <Collapse>
                                <Collapse.Panel header="Integration instructions" key="instructions">
                                    <Form.Item
                                        shouldUpdate={(prevValues, currentValues) =>
                                            prevValues.key !== currentValues.key
                                        }
                                    >
                                        <>
                                            {({ getFieldValue }) => {
                                                return submitDisabled ? (
                                                    <small>
                                                        Select either a person property or rollout percentage to save
                                                        your feature flag.
                                                    </small>
                                                ) : (
                                                    <span>
                                                        <br />
                                                        Example implementation:{' '}
                                                        <Snippet flagKey={getFieldValue('key')} />
                                                    </span>
                                                )
                                            }}
                                        </>
                                    </Form.Item>
                                </Collapse.Panel>
                            </Collapse>
                        </Col>
                        <Col span={24} md={12}>
                            <h3 className="l3">Release match groups ({featureFlag.filters.groups.length})</h3>
                            <div className="text-muted mb">
                                Specify which users or groups of users to which you want to release this flag.
                            </div>
                            {featureFlag.filters.groups.map((group, index) => (
                                <Card
                                    style={{ position: 'relative', marginBottom: 32 }}
                                    key={`${index}-${groups.length}`}
                                >
                                    {featureFlag.filters.groups.length > 1 && (
                                        <CloseButton
                                            style={{ position: 'absolute', top: 0, right: 0, margin: 4 }}
                                            onClick={() => removeMatchGroup(index)}
                                        />
                                    )}

                                    <Form.Item label="Filter by user properties" style={{ position: 'relative' }}>
                                        <PropertyFilters
                                            pageKey={`feature-flag-${featureFlag.id}-${index}-${groups.length}`}
                                            propertyFilters={group?.properties}
                                            onChange={(properties: PropertyFilter[]) =>
                                                updateMatchGroup(index, undefined, properties)
                                            }
                                            endpoint="person"
                                            showConditionBadge
                                        />
                                    </Form.Item>

                                    <Form.Item
                                        label="Roll out feature only to percentage of this match group"
                                        style={{ marginBottom: 0 }}
                                    >
                                        <>
                                            <Switch
                                                checked={!!group.rollout_percentage}
                                                onChange={(checked) =>
                                                    checked
                                                        ? updateMatchGroup(index, 30)
                                                        : updateMatchGroup(index, null)
                                                }
                                                data-attr="feature-flag-switch"
                                            />
                                            {group.rollout_percentage != null && (
                                                <Slider
                                                    tooltipPlacement="bottom"
                                                    tipFormatter={(value) => value + '%'}
                                                    tooltipVisible
                                                    value={group.rollout_percentage}
                                                    onChange={(value: number) => {
                                                        updateMatchGroup(index, value)
                                                    }}
                                                />
                                            )}
                                        </>
                                    </Form.Item>

                                    {index === featureFlag.filters.groups.length - 1 && (
                                        <Button style={{ position: 'absolute', marginTop: 8 }} onClick={addMatchGroup}>
                                            +
                                        </Button>
                                    )}
                                </Card>
                            ))}
                            <Form.Item className="text-right">
                                <Button
                                    disabled={submitDisabled}
                                    icon={<SaveOutlined />}
                                    htmlType="submit"
                                    style={{ marginRight: 16 }}
                                >
                                    Save changes and continue editing
                                </Button>
                                <Button
                                    disabled={submitDisabled}
                                    icon={<SaveOutlined />}
                                    htmlType="submit"
                                    type="primary"
                                    data-attr="feature-flag-submit"
                                >
                                    Save changes
                                </Button>
                            </Form.Item>
                        </Col>
                    </Row>
                </Form>
            ) : (
                <SceneLoading />
            )}
        </>
    )
}
