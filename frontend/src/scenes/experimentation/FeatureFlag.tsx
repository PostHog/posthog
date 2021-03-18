import React from 'react'
import { Input, Button, Form, Switch, Slider, Card, Row, Col, Collapse, Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { SceneLoading } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DeleteOutlined, SaveOutlined, PlusOutlined } from '@ant-design/icons'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { featureFlagLogic } from './featureFlagLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilter } from '~/types'
import './FeatureFlag.scss'
import Checkbox from 'antd/lib/checkbox/Checkbox'

function Snippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`if (posthog.isFeatureEnabled('${flagKey ?? ''}')) {
    // run your activation code here
}`}
        </CodeSnippet>
    )
}

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
        <div className="feature-flag">
            {featureFlag ? (
                <Form
                    layout="vertical"
                    form={form}
                    initialValues={{ name: featureFlag.name, key: featureFlag.key, active: featureFlag.active }}
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
                    <PageHeader
                        title="Feature Flag"
                        buttons={
                            <div style={{ display: 'flex' }}>
                                <Form.Item className="enabled-switch">
                                    <Form.Item
                                        shouldUpdate={(prevValues, currentValues) =>
                                            prevValues.active !== currentValues.active
                                        }
                                        style={{ marginBottom: 0, marginRight: 6 }}
                                    >
                                        {({ getFieldValue }) => {
                                            return (
                                                <span className="ant-form-item-label" style={{ lineHeight: '1.5rem' }}>
                                                    {getFieldValue('active') ? (
                                                        <span className="text-success">Enabled</span>
                                                    ) : (
                                                        <span className="text-danger">Disabled</span>
                                                    )}
                                                </span>
                                            )
                                        }}
                                    </Form.Item>
                                    <Form.Item name="active" noStyle valuePropName="checked">
                                        <Switch />
                                    </Form.Item>
                                </Form.Item>
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

                            <Collapse>
                                <Collapse.Panel header="Integration instructions" key="instructions">
                                    <Form.Item
                                        shouldUpdate={(prevValues, currentValues) =>
                                            prevValues.key !== currentValues.key
                                        }
                                    >
                                        {({ getFieldValue }) => {
                                            return submitDisabled ? (
                                                <small>
                                                    Select either a person property or rollout percentage to save your
                                                    feature flag.
                                                </small>
                                            ) : (
                                                <span>
                                                    <br />
                                                    Example implementation: <Snippet flagKey={getFieldValue('key')} />
                                                </span>
                                            )
                                        }}
                                    </Form.Item>
                                </Collapse.Panel>
                            </Collapse>
                        </Col>
                        <Col span={24} md={12}>
                            <h3 className="l3">Release condition groups ({featureFlag.filters.groups.length})</h3>
                            <div className="text-muted mb">
                                Specify which users or groups of users to which you want to release this flag.
                            </div>
                            {featureFlag.filters.groups.map((group, index) => (
                                <Card
                                    style={{ position: 'relative', marginBottom: 32, paddingBottom: 48 }}
                                    key={`${index}-${groups.length}`}
                                >
                                    {featureFlag.filters.groups.length > 1 && (
                                        <>
                                            <span style={{ position: 'absolute', top: 0, right: 0, margin: 4 }}>
                                                <Tooltip title="Delete this match group" placement="bottomLeft">
                                                    <Button
                                                        type="link"
                                                        icon={<DeleteOutlined />}
                                                        onClick={() => removeMatchGroup(index)}
                                                        style={{ color: 'var(--danger)' }}
                                                    />
                                                </Tooltip>
                                            </span>

                                            <div className="mb">
                                                <b>
                                                    Group
                                                    <span
                                                        className="simple-tag tag-light-lilac"
                                                        style={{ marginLeft: 8 }}
                                                    >
                                                        {index + 1}
                                                    </span>
                                                </b>
                                            </div>
                                        </>
                                    )}

                                    <Form.Item style={{ position: 'relative' }}>
                                        {group.properties?.length ? (
                                            <b>Matching users with filters</b>
                                        ) : (
                                            <b>
                                                {featureFlag.filters.groups.length > 1 ? 'Group will match ' : 'Match '}
                                                <span style={{ color: 'var(--warning)' }}>all users</span>
                                            </b>
                                        )}
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

                                    <Form.Item style={{ marginBottom: 0 }}>
                                        <>
                                            <Checkbox
                                                checked={!!group.rollout_percentage}
                                                onChange={(e) =>
                                                    e.target.checked
                                                        ? updateMatchGroup(index, 30)
                                                        : updateMatchGroup(index, null)
                                                }
                                                data-attr="feature-flag-switch"
                                            >
                                                <b>
                                                    Roll out to only a percentage of users
                                                    {featureFlag.filters.groups.length > 1 && ' in this group'}
                                                </b>
                                            </Checkbox>
                                            {group.rollout_percentage === null ? (
                                                <div className="mt">
                                                    Rolling out to <b>100%</b> of users
                                                    {featureFlag.filters.groups.length > 1 && ' in this group'}
                                                </div>
                                            ) : (
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
                                </Card>
                            ))}
                            <Button
                                type="dashed"
                                block
                                icon={<PlusOutlined />}
                                onClick={addMatchGroup}
                                style={{ marginBottom: 32 }}
                            >
                                Add Group
                            </Button>
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
                // TODO: This should be skeleton loaders
                <SceneLoading />
            )}
        </div>
    )
}
