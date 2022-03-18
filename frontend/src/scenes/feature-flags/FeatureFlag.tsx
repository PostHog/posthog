import React, { useState } from 'react'
import { Form, Group } from 'kea-forms'
import { Input, Button, Slider, Card, Row, Col, Collapse, Radio, InputNumber, Popconfirm, Select } from 'antd'
import { useActions, useValues } from 'kea'
import { capitalizeFirstLetter, SceneLoading } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import {
    DeleteOutlined,
    SaveOutlined,
    PlusOutlined,
    ApiFilled,
    MergeCellsOutlined,
    LockOutlined,
} from '@ant-design/icons'
import { featureFlagLogic, FeatureFlagLogicProps } from './featureFlagLogic'
import { PageHeader } from 'lib/components/PageHeader'
import './FeatureFlag.scss'
import { IconOpenInNew, IconJavascript, IconPython, IconCopy, IconDelete } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { APISnippet, JSSnippet, PythonSnippet, UTM_TAGS } from 'scenes/feature-flags/FeatureFlagSnippets'
import { LemonSpacer } from 'lib/components/LemonRow'
import { groupsModel } from '~/models/groupsModel'
import { GroupsIntroductionOption } from 'lib/introductions/GroupsIntroductionOption'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature } from '~/types'
import { Link } from 'lib/components/Link'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { Field } from 'lib/forms/Field'

export const scene: SceneExport = {
    component: FeatureFlag,
    logic: featureFlagLogic,
    paramsToProps: ({ params: { id } }) => ({ id: id ? parseInt(id) : 'new' }),
}

function focusVariantKeyField(index: number): void {
    setTimeout(
        () => document.querySelector<HTMLElement>(`.variant-form-list input[data-key-index="${index}"]`)?.focus(),
        50
    )
}

export function FeatureFlag({ id }: { id?: string } = {}): JSX.Element {
    const logicProps: FeatureFlagLogicProps = { id: id ? parseInt(id) : 'new' }
    const {
        featureFlag,
        multivariateEnabled,
        variants,
        nonEmptyVariants,
        areVariantRolloutsValid,
        variantRolloutSum,
        groupTypes,
        aggregationTargetName,
        taxonomicGroupTypes,
        featureFlagLoading,
    } = useValues(featureFlagLogic(logicProps))
    const {
        addConditionSet,
        updateConditionSet,
        removeConditionSet,
        duplicateConditionSet,
        deleteFeatureFlag,
        setMultivariateEnabled,
        addVariant,
        removeVariant,
        distributeVariantsEqually,
        setAggregationGroupTypeIndex,
    } = useActions(featureFlagLogic(logicProps))
    const { showGroupsOptions, aggregationLabel } = useValues(groupsModel)
    const { hasAvailableFeature, upgradeLink } = useValues(userLogic)

    // whether the key for an existing flag is being changed
    const [hasKeyChanged, setHasKeyChanged] = useState(false)
    // whether to warn the user that their variants will be lost
    const [showVariantDiscardWarning, setShowVariantDiscardWarning] = useState(false)

    // :KLUDGE: Match by select only allows Select.Option as children, so render groups option directly rather than as a child
    const matchByGroupsIntroductionOption = GroupsIntroductionOption({ value: -2 })

    return (
        <div className="feature-flag">
            {featureFlag ? (
                <Form
                    logic={featureFlagLogic}
                    props={logicProps}
                    formKey="featureFlag"
                    className="ant-form-vertical ant-form-hide-required-mark"
                    // scrollToFirstError
                >
                    <PageHeader
                        title="Feature Flag"
                        buttons={
                            <div style={{ display: 'flex' }}>
                                <Field name="active">
                                    {({ value, onValueChange }) => (
                                        <LemonSwitch
                                            checked={value}
                                            onChange={onValueChange}
                                            label={
                                                value ? (
                                                    <span className="text-success">Enabled</span>
                                                ) : (
                                                    <span className="text-danger">Disabled</span>
                                                )
                                            }
                                        />
                                    )}
                                </Field>
                                {featureFlag?.id && (
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
                                    loading={featureFlagLoading}
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
                            <Field
                                name="key"
                                label="Key (must be unique)"
                                validateStatus={hasKeyChanged ? 'warning' : undefined}
                                hint={
                                    hasKeyChanged && id !== 'new' ? (
                                        <small>
                                            <b>Warning! </b>Changing this key will
                                            <a
                                                href={`https://posthog.com/docs/features/feature-flags${UTM_TAGS}#feature-flag-persistence`}
                                                target="_blank"
                                                rel="noopener"
                                            >
                                                {' '}
                                                affect the persistence of your flag <IconOpenInNew />
                                            </a>
                                        </small>
                                    ) : undefined
                                }
                            >
                                {({ value, onChange }) => (
                                    <Input
                                        value={value}
                                        onChange={(e) => {
                                            if (e.target.value !== value) {
                                                setHasKeyChanged(true)
                                            }
                                            onChange(e)
                                        }}
                                        data-attr="feature-flag-key"
                                        className="ph-ignore-input"
                                        autoFocus
                                        placeholder="examples: new-landing-page, betaFeature, ab_test_1"
                                        autoComplete="off"
                                        autoCapitalize="off"
                                        autoCorrect="off"
                                        spellCheck={false}
                                    />
                                )}
                            </Field>

                            <Field name="name" label="Description">
                                {({ value, onChange }) => (
                                    <Input.TextArea
                                        value={value}
                                        onChange={onChange}
                                        className="ph-ignore-input"
                                        data-attr="feature-flag-description"
                                        placeholder="Adding a helpful description can ensure others know what this feature is for."
                                    />
                                )}
                            </Field>
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
                                    <JSSnippet flagKey={featureFlag.key || 'my-flag'} />
                                </Collapse.Panel>
                                <Collapse.Panel
                                    header={
                                        <div style={{ display: 'flex', fontWeight: 'bold', alignItems: 'center' }}>
                                            <IconPython style={{ marginRight: 6 }} /> Python integration instructions
                                        </div>
                                    }
                                    key="python"
                                >
                                    <PythonSnippet flagKey={featureFlag.key || 'my-flag'} />
                                </Collapse.Panel>
                                <Collapse.Panel
                                    header={
                                        <div style={{ display: 'flex', fontWeight: 'bold', alignItems: 'center' }}>
                                            <ApiFilled style={{ marginRight: 6 }} /> API integration instructions
                                        </div>
                                    }
                                    key="api"
                                >
                                    <APISnippet />
                                </Collapse.Panel>
                            </Collapse>
                        </Col>
                    </Row>

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
                                                <Tooltip
                                                    title={
                                                        hasAvailableFeature(AvailableFeature.MULTIVARIATE_FLAGS)
                                                            ? ''
                                                            : 'This feature is not available on your current plan.'
                                                    }
                                                >
                                                    <div>
                                                        {!hasAvailableFeature(AvailableFeature.MULTIVARIATE_FLAGS) && (
                                                            <Link to={upgradeLink} target="_blank">
                                                                <LockOutlined
                                                                    style={{ marginRight: 4, color: 'var(--warning)' }}
                                                                />
                                                            </Link>
                                                        )}
                                                        String value (Multivariate test){' '}
                                                        <LemonTag type="warning">Beta</LemonTag>
                                                    </div>
                                                </Tooltip>
                                            ),
                                            value: true,
                                            disabled: !hasAvailableFeature(AvailableFeature.MULTIVARIATE_FLAGS),
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
                                {variants.map((_, index) => (
                                    <Group key={index} name={['filters', 'multivariate', 'variants', index]}>
                                        <Row gutter={8}>
                                            <Col span={7}>
                                                <Field name="key">
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
                                                </Field>
                                            </Col>
                                            <Col span={7}>
                                                <Field name="name">
                                                    <Input
                                                        data-attr="feature-flag-variant-name"
                                                        className="ph-ignore-input"
                                                        placeholder="Description"
                                                    />
                                                </Field>
                                            </Col>
                                            <Col span={7}>
                                                <Field name="rollout_percentage">
                                                    {({ value, onValueChange }) => (
                                                        <Slider
                                                            tooltipPlacement="top"
                                                            value={value}
                                                            onChange={onValueChange}
                                                        />
                                                    )}
                                                </Field>
                                            </Col>
                                            <Col span={2}>
                                                <Field name="rollout_percentage">
                                                    {({ value, onValueChange }) => (
                                                        <InputNumber
                                                            min={0}
                                                            max={100}
                                                            value={value}
                                                            onChange={(changedValue) => {
                                                                if (
                                                                    changedValue !== null &&
                                                                    changedValue !== undefined
                                                                ) {
                                                                    const valueInt = parseInt(changedValue.toString())
                                                                    if (!isNaN(valueInt)) {
                                                                        onValueChange(valueInt)
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
                                                    )}
                                                </Field>
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
                                    </Group>
                                ))}
                                {variants.length > 0 && !areVariantRolloutsValid && (
                                    <p className="text-danger">
                                        Percentage rollouts for variants must sum to 100 (currently {variantRolloutSum}
                                        ).
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
                                        featureFlag.filters?.aggregation_group_type_index != null
                                            ? featureFlag.filters?.aggregation_group_type_index
                                            : -1
                                    }
                                    onChange={(value) => {
                                        const groupTypeIndex = value !== -1 ? value : null
                                        setAggregationGroupTypeIndex(groupTypeIndex)
                                    }}
                                    style={{ marginLeft: 8 }}
                                    data-attr="feature-flag-aggregation-filter"
                                    dropdownMatchSelectWidth={false}
                                    dropdownAlign={{
                                        // Align this dropdown by the right-hand-side of button
                                        points: ['tr', 'br'],
                                    }}
                                >
                                    <Select.Option key={-1} value={-1}>
                                        Users
                                    </Select.Option>
                                    {groupTypes.map((groupType) => (
                                        <Select.Option
                                            key={groupType.group_type_index}
                                            value={groupType.group_type_index}
                                        >
                                            {capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural)}
                                        </Select.Option>
                                    ))}
                                    {matchByGroupsIntroductionOption}
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
                                        <Row align="middle">
                                            <Tooltip title="Duplicate this condition set" placement="bottomLeft">
                                                <LemonButton
                                                    icon={<IconCopy />}
                                                    compact
                                                    onClick={() => duplicateConditionSet(index)}
                                                />
                                            </Tooltip>
                                            {featureFlag.filters.groups.length > 1 && (
                                                <Tooltip title="Delete this condition set" placement="bottomLeft">
                                                    <LemonButton
                                                        icon={<IconDelete />}
                                                        compact
                                                        onClick={() => removeConditionSet(index)}
                                                    />
                                                </Tooltip>
                                            )}
                                        </Row>
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
                    <div className="text-right">
                        <Button
                            icon={<SaveOutlined />}
                            htmlType="submit"
                            type="primary"
                            data-attr="feature-flag-submit-bottom"
                        >
                            Save changes
                        </Button>
                    </div>
                </Form>
            ) : (
                // TODO: This should be skeleton loaders
                <SceneLoading />
            )}
        </div>
    )
}
