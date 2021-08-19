import React, { useState } from 'react'
import { Input, Button, Form, Switch, Slider, Card, Row, Col, Collapse } from 'antd'
import { useActions, useValues } from 'kea'
import { SceneLoading } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DeleteOutlined, SaveOutlined, PlusOutlined, ApiFilled } from '@ant-design/icons'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { featureFlagLogic } from './featureFlagLogic'
import { PageHeader } from 'lib/components/PageHeader'
import './FeatureFlag.scss'
import Checkbox from 'antd/lib/checkbox/Checkbox'
import { IconExternalLink, IconJavascript, IconPython } from 'lib/components/icons'
import { teamLogic } from 'scenes/teamLogic'
import { Tooltip } from 'lib/components/Tooltip'

const UTM_TAGS = '?utm_medium=in-product&utm_campaign=feature-flag'

function JSSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.JavaScript} wrap>
                {`if (posthog.isFeatureEnabled('${flagKey ?? ''}')) {
    // run your activation code here
}`}
            </CodeSnippet>
            <div className="mt">
                Need more information?{' '}
                <a
                    target="_blank"
                    rel="noopener"
                    href={`https://posthog.com/docs/integrations/js-integration${UTM_TAGS}#feature-flags`}
                >
                    Check the docs <IconExternalLink />
                </a>
            </div>
        </>
    )
}

function PythonSnippet({ flagKey }: { flagKey: string }): JSX.Element {
    return (
        <>
            <CodeSnippet language={Language.Python} wrap>
                {`if posthog.feature_enabled("${flagKey}", "user_distinct_id"):
    runAwesomeFeature()
`}
            </CodeSnippet>
            <div className="mt">
                Need more information?{' '}
                <a
                    target="_blank"
                    rel="noopener"
                    href={`https://posthog.com/docs/integrations/python-integration${UTM_TAGS}#feature-flags`}
                >
                    Check the docs <IconExternalLink />
                </a>
            </div>
        </>
    )
}

function APISnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    return (
        <>
            <CodeSnippet language={Language.Bash} wrap>
                {`curl ${window.location.origin}/decide/ \\
-X POST -H 'Content-Type: application/json' \\
-d '{
    "api_key": "${currentTeam ? currentTeam.api_token : '[project_api_key]'}",
    "distinct_id": "[user distinct id]"
}'
                `}
            </CodeSnippet>
            <div className="mt">
                Need more information?{' '}
                <a target="_blank" rel="noopener" href={`https://posthog.com/docs/api/feature-flags${UTM_TAGS}`}>
                    Check the docs <IconExternalLink />
                </a>
            </div>
        </>
    )
}

export function FeatureFlag(): JSX.Element {
    const [form] = Form.useForm()
    const { featureFlag, featureFlagId } = useValues(featureFlagLogic)
    const { addMatchGroup, updateMatchGroup, removeMatchGroup, saveFeatureFlag, deleteFeatureFlag } = useActions(
        featureFlagLogic
    )

    const [hasKeyChanged, setHasKeyChanged] = useState(false) // whether the key for an existing flag is being changed

    return (
        <div className="feature-flag">
            {featureFlag ? (
                <Form
                    layout="vertical"
                    form={form}
                    initialValues={{ name: featureFlag.name, key: featureFlag.key, active: featureFlag.active }}
                    onValuesChange={(newValues) => {
                        if (featureFlagId !== 'new' && newValues.key) {
                            setHasKeyChanged(newValues.key !== featureFlag.key)
                        }
                    }}
                    onFinish={(values) =>
                        saveFeatureFlag({
                            ...featureFlag,
                            ...values,
                            filters: featureFlag.filters,
                        })
                    }
                    requiredMark={false}
                    scrollToFirstError
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
                                    icon={<SaveOutlined />}
                                    type="primary"
                                    data-attr="feature-flag-submit"
                                    htmlType="submit"
                                >
                                    Save changes
                                </Button>
                            </div>
                        }
                    />
                    <h3 className="l3">General configuration</h3>
                    <div className="text-muted mb">
                        General settings for your feature flag and integration instructions.
                    </div>
                    <Row gutter={16} style={{ marginBottom: 32 }}>
                        <Col span={12}>
                            <Form.Item
                                name="key"
                                label="Key (must be unique)"
                                rules={[
                                    { required: true, message: 'You need to set a key.' },
                                    {
                                        pattern: /^([A-z]|[a-z]|[0-9]|-|_)+$/,
                                        message: 'Only letters, numbers, hyphens (-) & underscores (_) are allowed.',
                                    },
                                ]}
                                validateStatus={hasKeyChanged ? 'warning' : undefined}
                                help={
                                    hasKeyChanged ? (
                                        <small>
                                            <b>Warning! </b>Changing this key will
                                            <a
                                                href={`https://posthog.com/docs/features/feature-flags${UTM_TAGS}#feature-flag-persistence`}
                                                target="_blank"
                                                rel="noopener"
                                            >
                                                {' '}
                                                affect the persistence of your flag <IconExternalLink />
                                            </a>
                                        </small>
                                    ) : undefined
                                }
                            >
                                <Input
                                    data-attr="feature-flag-key"
                                    className="ph-ignore-input"
                                    autoFocus
                                    placeholder="examples: new-landing-page, betaFeature, ab_test_1"
                                    autoComplete="off"
                                    autoCapitalize="off"
                                    autoCorrect="off"
                                    spellCheck={false}
                                />
                            </Form.Item>

                            <Form.Item name="name" label="Description">
                                <Input.TextArea
                                    className="ph-ignore-input"
                                    data-attr="feature-flag-description"
                                    placeholder="Adding a helpful description can ensure others know what this feature is for."
                                />
                            </Form.Item>
                        </Col>
                        <Col span={12} style={{ paddingTop: 31 }}>
                            <Collapse>
                                <Collapse.Panel
                                    header={
                                        <div style={{ display: 'flex', fontWeight: 'bold', alignItems: 'center' }}>
                                            <IconJavascript style={{ marginRight: 6 }} /> Javascript integration
                                            instructions
                                        </div>
                                    }
                                    key="js"
                                >
                                    <Form.Item
                                        shouldUpdate={(prevValues, currentValues) =>
                                            prevValues.key !== currentValues.key
                                        }
                                    >
                                        {({ getFieldValue }) => <JSSnippet flagKey={getFieldValue('key')} />}
                                    </Form.Item>
                                </Collapse.Panel>
                                <Collapse.Panel
                                    header={
                                        <div style={{ display: 'flex', fontWeight: 'bold', alignItems: 'center' }}>
                                            <IconPython style={{ marginRight: 6 }} /> Python integration instructions
                                        </div>
                                    }
                                    key="python"
                                >
                                    <Form.Item
                                        shouldUpdate={(prevValues, currentValues) =>
                                            prevValues.key !== currentValues.key
                                        }
                                    >
                                        {({ getFieldValue }) => <PythonSnippet flagKey={getFieldValue('key')} />}
                                    </Form.Item>
                                </Collapse.Panel>
                                <Collapse.Panel
                                    header={
                                        <div style={{ display: 'flex', fontWeight: 'bold', alignItems: 'center' }}>
                                            <ApiFilled style={{ marginRight: 6 }} /> API integration instructions
                                        </div>
                                    }
                                    key="api"
                                >
                                    <Form.Item
                                        shouldUpdate={(prevValues, currentValues) =>
                                            prevValues.key !== currentValues.key
                                        }
                                    >
                                        <APISnippet />
                                    </Form.Item>
                                </Collapse.Panel>
                            </Collapse>
                        </Col>
                    </Row>

                    <h3 className="l3">Release condition groups ({featureFlag.filters.groups.length})</h3>
                    <div className="text-muted mb">
                        Specify which users or groups of users to which you want to release this flag.
                    </div>
                    <Button
                        type="dashed"
                        block
                        icon={<PlusOutlined />}
                        onClick={addMatchGroup}
                        style={{ marginBottom: 16 }}
                    >
                        Add Group
                    </Button>
                    <Row gutter={16}>
                        {featureFlag.filters.groups.map((group, index) => (
                            <Col span={24} md={12} key={`${index}-${featureFlag.filters.groups.length}`}>
                                <Card style={{ position: 'relative', marginBottom: 32, paddingBottom: 16 }}>
                                    {index > 0 && <div className="stateful-badge pos-center-end or">OR</div>}
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

                                    <Form.Item style={{ position: 'relative', marginBottom: 16 }}>
                                        {group.properties?.length ? (
                                            <b>Matching users with filters</b>
                                        ) : (
                                            <b>
                                                {featureFlag.filters.groups.length > 1 ? 'Group will match ' : 'Match '}
                                                <span style={{ color: 'var(--warning)' }}>all users</span>
                                            </b>
                                        )}
                                        <PropertyFilters
                                            pageKey={`feature-flag-${featureFlag.id}-${index}-${featureFlag.filters.groups.length}`}
                                            propertyFilters={group?.properties}
                                            onChange={(properties) => updateMatchGroup(index, undefined, properties)}
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
                                                    tooltipPlacement="top"
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
                            </Col>
                        ))}
                    </Row>
                    <Form.Item className="text-right">
                        <Button
                            icon={<SaveOutlined />}
                            htmlType="submit"
                            type="primary"
                            data-attr="feature-flag-submit-bottom"
                        >
                            Save changes
                        </Button>
                    </Form.Item>
                </Form>
            ) : (
                // TODO: This should be skeleton loaders
                <SceneLoading />
            )}
        </div>
    )
}
