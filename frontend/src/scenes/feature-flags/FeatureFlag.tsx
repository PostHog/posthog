import React, { useEffect, useState } from 'react'
import {
    Input,
    Button,
    Form,
    Switch,
    Slider,
    Card,
    Row,
    Col,
    Collapse,
    Radio,
    InputNumber,
    Popconfirm,
    Tag,
    Select,
} from 'antd'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter, SceneLoading } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import {
    DeleteOutlined,
    CopyOutlined,
    SaveOutlined,
    PlusOutlined,
    ApiFilled,
    MergeCellsOutlined,
} from '@ant-design/icons'
import { featureFlagLogic } from './featureFlagLogic'
import { featureFlagLogic as featureFlagClientLogic } from 'lib/logic/featureFlagLogic'
import { PageHeader } from 'lib/components/PageHeader'
import './FeatureFlag.scss'
import { IconExternalLink, IconJavascript, IconPython } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { FEATURE_FLAGS } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'
import { APISnippet, JSSnippet, PythonSnippet, UTM_TAGS } from 'scenes/feature-flags/FeatureFlagSnippets'
import { LemonSpacer } from 'lib/components/LemonRow'
import { groupsModel } from '~/models/groupsModel'

export const scene: SceneExport = {
    component: FeatureFlag,
    logic: featureFlagLogic,
}

function focusVariantKeyField(index: number): void {
    setTimeout(
        () => document.querySelector<HTMLElement>(`.variant-form-list input[data-key-index="${index}"]`)?.focus(),
        50
    )
}

export function FeatureFlag(): JSX.Element {
    const [form] = Form.useForm()
    const {
        featureFlag,
        featureFlagId,
        multivariateEnabled,
        variants,
        nonEmptyVariants,
        areVariantRolloutsValid,
        variantRolloutSum,
        groupTypes,
        aggregationTargetName,
        taxonomicGroupTypes,
    } = useValues(featureFlagLogic)
    const {
        addConditionSet,
        updateConditionSet,
        removeConditionSet,
        duplicateConditionSet,
        saveFeatureFlag,
        deleteFeatureFlag,
        setMultivariateEnabled,
        addVariant,
        updateVariant,
        removeVariant,
        distributeVariantsEqually,
        setFeatureFlag,
        setAggregationGroupTypeIndex,
    } = useActions(featureFlagLogic)
    const { featureFlags: enabledFeatureFlags } = useValues(featureFlagClientLogic)
    const { showGroupsOptions } = useValues(groupsModel)

    // whether the key for an existing flag is being changed
    const [hasKeyChanged, setHasKeyChanged] = useState(false)
    // whether to warn the user that their variants will be lost
    const [showVariantDiscardWarning, setShowVariantDiscardWarning] = useState(false)

    useEffect(() => {
        form.setFieldsValue({ ...featureFlag })
    }, [featureFlag])

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
                        setFeatureFlag({ ...featureFlag, ...newValues })
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

                    {enabledFeatureFlags[FEATURE_FLAGS.MULTIVARIATE_SUPPORT] && (
                        <div className="mb-2">
                            <h3 className="l3">Served value</h3>
                            <div className="mb-05">
                                <Popconfirm
                                    placement="top"
                                    title="Change value type? The variants below will be lost."
                                    visible={showVariantDiscardWarning}
                                    onConfirm={() => {
                                        setMultivariateEnabled(false)
                                        setShowVariantDiscardWarning(false)
                                    }}
                                    onCancel={() => setShowVariantDiscardWarning(false)}
                                    okText="OK"
                                    cancelText="Cancel"
                                >
                                    <Radio.Group
                                        options={[
                                            {
                                                label: 'Boolean value (A/B test)',
                                                value: false,
                                            },
                                            {
                                                label: (
                                                    <div>
                                                        String value (Multivariate test){' '}
                                                        <Tag
                                                            color={'orange'}
                                                            style={{ fontSize: 12, fontWeight: 'bold' }}
                                                        >
                                                            ALPHA
                                                        </Tag>
                                                    </div>
                                                ),
                                                value: true,
                                            },
                                        ]}
                                        onChange={(e) => {
                                            const { value } = e.target
                                            if (value === false && nonEmptyVariants.length) {
                                                setShowVariantDiscardWarning(true)
                                            } else {
                                                setMultivariateEnabled(value)
                                                focusVariantKeyField(0)
                                            }
                                        }}
                                        value={multivariateEnabled}
                                        optionType="button"
                                    />
                                </Popconfirm>
                            </div>
                            <div className="text-muted mb">
                                {capitalizeFirstLetter(aggregationTargetName)} will be served{' '}
                                {multivariateEnabled ? (
                                    <>
                                        <strong>a variant key</strong> according to the below distribution
                                    </>
                                ) : (
                                    <strong>
                                        <code>true</code>
                                    </strong>
                                )}{' '}
                                if they match one or more release condition groups.
                            </div>
                            {multivariateEnabled && (
                                <div className="variant-form-list">
                                    <Row gutter={8} className="label-row">
                                        <Col span={7}>Variant key</Col>
                                        <Col span={7}>Description</Col>
                                        <Col span={9}>
                                            <span>Rollout percentage</span>
                                            <Button
                                                type="link"
                                                onClick={distributeVariantsEqually}
                                                icon={<MergeCellsOutlined />}
                                                style={{ padding: '0 0 0 0.5em' }}
                                                title="Distribute variants equally"
                                            >
                                                Distribute
                                            </Button>
                                        </Col>
                                    </Row>
                                    {variants.map(({ rollout_percentage }, index) => (
                                        <Form
                                            key={index}
                                            onValuesChange={(changedValues) => updateVariant(index, changedValues)}
                                            initialValues={variants[index]}
                                            validateTrigger={['onChange', 'onBlur']}
                                        >
                                            <Row gutter={8}>
                                                <Col span={7}>
                                                    <Form.Item
                                                        name="key"
                                                        rules={[
                                                            { required: true, message: 'Key should not be empty.' },
                                                            {
                                                                pattern: /^([A-z]|[a-z]|[0-9]|-|_)+$/,
                                                                message:
                                                                    'Only letters, numbers, hyphens (-) & underscores (_) are allowed.',
                                                            },
                                                        ]}
                                                    >
                                                        <Input
                                                            data-attr="feature-flag-variant-key"
                                                            data-key-index={index.toString()}
                                                            className="ph-ignore-input"
                                                            placeholder={`example-variant-${index + 1}`}
                                                            autoComplete="off"
                                                            autoCapitalize="off"
                                                            autoCorrect="off"
                                                            spellCheck={false}
                                                        />
                                                    </Form.Item>
                                                </Col>
                                                <Col span={7}>
                                                    <Form.Item name="name">
                                                        <Input
                                                            data-attr="feature-flag-variant-name"
                                                            className="ph-ignore-input"
                                                            placeholder="Description"
                                                        />
                                                    </Form.Item>
                                                </Col>
                                                <Col span={7}>
                                                    <Slider
                                                        tooltipPlacement="top"
                                                        value={rollout_percentage}
                                                        onChange={(value: number) =>
                                                            updateVariant(index, { rollout_percentage: value })
                                                        }
                                                    />
                                                </Col>
                                                <Col span={2}>
                                                    <InputNumber
                                                        min={0}
                                                        max={100}
                                                        value={rollout_percentage}
                                                        onChange={(value) => {
                                                            if (value !== null && value !== undefined) {
                                                                const valueInt = parseInt(value.toString())
                                                                if (!isNaN(valueInt)) {
                                                                    updateVariant(index, {
                                                                        rollout_percentage: valueInt,
                                                                    })
                                                                }
                                                            }
                                                        }}
                                                        style={{
                                                            width: '100%',
                                                            borderColor: areVariantRolloutsValid
                                                                ? undefined
                                                                : 'var(--danger)',
                                                        }}
                                                    />
                                                </Col>
                                                {variants.length > 1 && (
                                                    <Col span={1}>
                                                        <Tooltip title="Delete this variant" placement="bottomLeft">
                                                            <Button
                                                                type="link"
                                                                icon={<DeleteOutlined />}
                                                                onClick={() => removeVariant(index)}
                                                                style={{ color: 'var(--danger)' }}
                                                            />
                                                        </Tooltip>
                                                    </Col>
                                                )}
                                            </Row>
                                        </Form>
                                    ))}
                                    {variants.length > 0 && !areVariantRolloutsValid && (
                                        <p className="text-danger">
                                            Percentage rollouts for variants must sum to 100 (currently{' '}
                                            {variantRolloutSum}).
                                        </p>
                                    )}
                                    <Button
                                        type="dashed"
                                        block
                                        icon={<PlusOutlined />}
                                        onClick={() => {
                                            const newIndex = variants.length
                                            addVariant()
                                            focusVariantKeyField(newIndex)
                                        }}
                                        style={{ marginBottom: 16 }}
                                    >
                                        Add Variant
                                    </Button>
                                </div>
                            )}
                        </div>
                    )}

                    <div className="feature-flag-form-row">
                        <div>
                            <h3 className="l3">Release conditions</h3>
                            <div className="text-muted mb">
                                Specify the {aggregationTargetName} to which you want to release this flag. Note that
                                condition sets are rolled out independently of each other.
                            </div>
                        </div>
                        {showGroupsOptions && (
                            <div className="centered">
                                Match by
                                <Select
                                    value={
                                        featureFlag.filters.aggregation_group_type_index != null
                                            ? featureFlag.filters.aggregation_group_type_index
                                            : -1
                                    }
                                    onChange={(value) => {
                                        const groupTypeIndex = value !== -1 ? value : null
                                        setAggregationGroupTypeIndex(groupTypeIndex)
                                    }}
                                    style={{ marginLeft: 8 }}
                                    data-attr="feature-flag-aggregation-filter"
                                    dropdownMatchSelectWidth={false}
                                >
                                    <Select.Option key={-1} value={-1}>
                                        Users
                                    </Select.Option>
                                    {groupTypes.map((groupType) => (
                                        <Select.Option
                                            key={groupType.group_type_index}
                                            value={groupType.group_type_index}
                                        >
                                            {capitalizeFirstLetter(groupType.group_type)}(s)
                                        </Select.Option>
                                    ))}
                                </Select>
                            </div>
                        )}
                    </div>
                    <Row gutter={16}>
                        {featureFlag.filters.groups.map((group, index) => (
                            <Col span={24} md={24} key={`${index}-${featureFlag.filters.groups.length}`}>
                                {index > 0 && (
                                    <div style={{ display: 'flex', marginLeft: 16 }}>
                                        <div className="stateful-badge or-light-grey mb">OR</div>
                                    </div>
                                )}
                                <Card style={{ marginBottom: 16 }}>
                                    <div className="feature-flag-form-row" style={{ height: 24 }}>
                                        <div>
                                            <span className="simple-tag tag-light-blue" style={{ marginRight: 8 }}>
                                                Set {index + 1}
                                            </span>
                                            {group.properties?.length ? (
                                                <>
                                                    Matching <b>{aggregationTargetName}</b> with filters
                                                </>
                                            ) : (
                                                <>
                                                    Condition set will match <b>all {aggregationTargetName}</b>
                                                </>
                                            )}
                                        </div>
                                        <div>
                                            <Tooltip title="Duplicate this condition set" placement="bottomLeft">
                                                <Button
                                                    type="link"
                                                    icon={<CopyOutlined />}
                                                    style={{ width: 24, height: 24 }}
                                                    onClick={() => duplicateConditionSet(index)}
                                                />
                                            </Tooltip>
                                            {featureFlag.filters.groups.length > 1 && (
                                                <Tooltip title="Delete this condition set" placement="bottomLeft">
                                                    <Button
                                                        type="link"
                                                        icon={<DeleteOutlined />}
                                                        style={{ width: 24, height: 24 }}
                                                        onClick={() => removeConditionSet(index)}
                                                    />
                                                </Tooltip>
                                            )}
                                        </div>
                                    </div>

                                    <LemonSpacer large />
                                    <PropertyFilters
                                        style={{ marginLeft: 15 }}
                                        pageKey={`feature-flag-${featureFlag.id}-${index}-${
                                            featureFlag.filters.groups.length
                                        }-${featureFlag.filters.aggregation_group_type_index ?? ''}`}
                                        propertyFilters={group?.properties}
                                        onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                        taxonomicGroupTypes={taxonomicGroupTypes}
                                        showConditionBadge
                                        greyBadges
                                    />
                                    <LemonSpacer large />

                                    <div className="feature-flag-form-row">
                                        <div className="centered">
                                            Roll out to{' '}
                                            <InputNumber
                                                style={{ width: 100, marginLeft: 8, marginRight: 8 }}
                                                onChange={(value): void => {
                                                    updateConditionSet(index, value as number)
                                                }}
                                                value={
                                                    group.rollout_percentage != null ? group.rollout_percentage : 100
                                                }
                                                min={0}
                                                max={100}
                                                addonAfter="%"
                                            />{' '}
                                            of <b>{aggregationTargetName}</b> in this set
                                        </div>
                                    </div>
                                </Card>
                            </Col>
                        ))}
                    </Row>
                    <Card size="small" style={{ marginBottom: 16 }}>
                        <Button type="link" onClick={addConditionSet} style={{ marginLeft: 5 }}>
                            <PlusOutlined style={{ marginRight: 15 }} /> Add condition set
                        </Button>
                    </Card>
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
