import React, { useState } from 'react'
import { Form, Group } from 'kea-forms'
import { Button, Slider, Card, Row, Col, Radio, InputNumber, Popconfirm, Select, Divider, Tabs, Skeleton } from 'antd'
import { useActions, useValues } from 'kea'
import { alphabet, capitalizeFirstLetter } from 'lib/utils'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { DeleteOutlined, MergeCellsOutlined, LockOutlined } from '@ant-design/icons'
import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagInstructions } from './FeatureFlagInstructions'
import { PageHeader } from 'lib/components/PageHeader'
import './FeatureFlag.scss'
import { IconOpenInNew, IconCopy, IconDelete, IconPlus, IconPlusMini, IconSubArrowRight } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { SceneExport } from 'scenes/sceneTypes'
import { UTM_TAGS } from 'scenes/feature-flags/FeatureFlagSnippets'
import { LemonDivider } from 'lib/components/LemonDivider'
import { groupsModel } from '~/models/groupsModel'
import { GroupsIntroductionOption } from 'lib/introductions/GroupsIntroductionOption'
import { userLogic } from 'scenes/userLogic'
import { AnyPropertyFilter, AvailableFeature } from '~/types'
import { Link } from 'lib/components/Link'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { Field } from 'lib/forms/Field'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonCheckbox } from 'lib/components/LemonCheckbox'
import { EventBufferNotice } from 'scenes/events/EventBufferNotice'
import { AlertMessage } from 'lib/components/AlertMessage'
import { urls } from 'scenes/urls'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { router } from 'kea-router'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { Lettermark, LettermarkColor } from 'lib/components/Lettermark/Lettermark'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic as featureFlagLibLogic } from 'lib/logic/featureFlagLogic'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { FeatureFlagsTabs } from './featureFlagsLogic'
import { flagActivityDescriber } from './activityDescriptions'
import { allOperatorsToHumanName } from 'lib/components/DefinitionPopup/utils'
import { RecentFeatureFlagInsights } from './RecentFeatureFlagInsightsCard'
import { NotFound } from 'lib/components/NotFound'
import { cohortsModel } from '~/models/cohortsModel'

export const scene: SceneExport = {
    component: FeatureFlag,
    logic: featureFlagLogic,
    paramsToProps: ({ params: { id } }): typeof featureFlagLogic['props'] => ({
        id: id && id !== 'new' ? parseInt(id) : 'new',
    }),
}

function focusVariantKeyField(index: number): void {
    setTimeout(
        () => document.querySelector<HTMLElement>(`.variant-form-list input[data-key-index="${index}"]`)?.focus(),
        50
    )
}

export function FeatureFlag({ id }: { id?: string } = {}): JSX.Element {
    const { featureFlags } = useValues(featureFlagLibLogic)
    const {
        props,
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
        featureFlagMissing,
        isEditingFlag,
    } = useValues(featureFlagLogic)
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
        editFeatureFlag,
        loadFeatureFlag,
    } = useActions(featureFlagLogic)
    const { showGroupsOptions, aggregationLabel } = useValues(groupsModel)
    const { hasAvailableFeature, upgradeLink } = useValues(userLogic)

    // whether the key for an existing flag is being changed
    const [hasKeyChanged, setHasKeyChanged] = useState(false)
    // whether to warn the user that their variants will be lost
    const [showVariantDiscardWarning, setShowVariantDiscardWarning] = useState(false)
    const [activeTab, setActiveTab] = useState(FeatureFlagsTabs.OVERVIEW)

    // :KLUDGE: Match by select only allows Select.Option as children, so render groups option directly rather than as a child
    const matchByGroupsIntroductionOption = GroupsIntroductionOption({ value: -2 })
    const isNewFeatureFlag = id === 'new' || id === undefined

    if (featureFlagMissing) {
        return <NotFound object={'feature flag'} />
    }
    if (featureFlagLoading) {
        return (
            // TODO: This should be skeleton loaders
            <SpinnerOverlay />
        )
    }

    return (
        <>
            {featureFlags[FEATURE_FLAGS.FEATURE_FLAGS_UX] ? (
                <div className="feature-flag">
                    {isNewFeatureFlag || isEditingFlag ? (
                        <Form
                            logic={featureFlagLogic}
                            props={props}
                            formKey="featureFlag"
                            enableFormOnSubmit
                            className="space-y-4"
                        >
                            <PageHeader
                                title={isNewFeatureFlag ? 'New feature flag' : featureFlag.key || 'Untitled'}
                                buttons={
                                    <div className="flex items-center gap-2">
                                        <LemonButton
                                            data-attr="cancel-feature-flag"
                                            type="secondary"
                                            onClick={() => {
                                                if (isEditingFlag) {
                                                    editFeatureFlag(false)
                                                    loadFeatureFlag()
                                                } else {
                                                    router.actions.push(urls.featureFlags())
                                                }
                                            }}
                                            disabled={featureFlagLoading}
                                        >
                                            Cancel
                                        </LemonButton>
                                        <LemonButton
                                            type="primary"
                                            data-attr="save-feature-flag"
                                            htmlType="submit"
                                            loading={featureFlagLoading}
                                            disabled={featureFlagLoading}
                                        >
                                            Save
                                        </LemonButton>
                                    </div>
                                }
                            />
                            <Divider />
                            {featureFlag.experiment_set && featureFlag.experiment_set?.length > 0 && (
                                <AlertMessage type="warning">
                                    This feature flag is linked to an experiment. It's recommended to only make changes
                                    to this flag{' '}
                                    <Link to={urls.experiment(featureFlag.experiment_set[0])}>
                                        using the experiment creation screen.
                                    </Link>
                                </AlertMessage>
                            )}
                            <EventBufferNotice additionalInfo=", meaning it can take around 60 seconds for some flags to update for recently-identified persons. To sidestep this, you can choose to override server properties when requesting the feature flag." />
                            <Row gutter={16} style={{ marginBottom: 32 }}>
                                <Col span={12} className="space-y-4">
                                    <Field
                                        name="key"
                                        label="Key"
                                        help={
                                            hasKeyChanged && id !== 'new' ? (
                                                <span className="text-warning">
                                                    <b>Warning! </b>Changing this key will
                                                    <a
                                                        href={`https://posthog.com/docs/features/feature-flags${UTM_TAGS}#feature-flag-persistence`}
                                                        target="_blank"
                                                        rel="noopener"
                                                    >
                                                        {' '}
                                                        affect the persistence of your flag <IconOpenInNew />
                                                    </a>
                                                </span>
                                            ) : undefined
                                        }
                                    >
                                        {({ value, onChange }) => (
                                            <>
                                                <LemonInput
                                                    value={value}
                                                    onChange={(v) => {
                                                        if (v !== value) {
                                                            setHasKeyChanged(true)
                                                        }
                                                        onChange(v)
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
                                                <span style={{ fontSize: 13 }} className="text-muted">
                                                    Feature flag keys must be unique
                                                </span>
                                            </>
                                        )}
                                    </Field>

                                    <Field name="name" label="Description">
                                        <LemonTextArea
                                            className="ph-ignore-input"
                                            data-attr="feature-flag-description"
                                            defaultValue={featureFlag.name || ''}
                                        />
                                    </Field>
                                    <Field name="ensure_experience_continuity">
                                        {({ value, onChange }) => (
                                            <div className="border rounded p-4">
                                                <LemonCheckbox
                                                    id="continuity-checkbox"
                                                    label="Persist flag across authentication steps"
                                                    onChange={() => onChange(!value)}
                                                    fullWidth
                                                    checked={value}
                                                />
                                                <div className="text-muted text-sm pl-7">
                                                    If your feature flag is applied prior to an identify or
                                                    authentication event, use this to ensure that feature flags are not
                                                    reset after a person is identified. This ensures the experience for
                                                    the anonymous person is carried forward to the authenticated person.
                                                </div>
                                            </div>
                                        )}
                                    </Field>
                                    <Field name="active">
                                        {({ value, onChange }) => (
                                            <div className="border rounded p-4">
                                                <LemonCheckbox
                                                    id="flag-enabled-checkbox"
                                                    label="Enable feature flag"
                                                    onChange={() => onChange(!value)}
                                                    checked={value}
                                                />
                                            </div>
                                        )}
                                    </Field>
                                </Col>
                                <Col span={12}>
                                    <FeatureFlagInstructions featureFlagKey={featureFlag.key || 'my-flag'} />
                                </Col>
                            </Row>
                            <Divider />
                            <FeatureFlagRollout />
                            <Divider />
                            <FeatureFlagReleaseConditions />
                            <LemonDivider className="mt-8" />
                            <div className="flex items-center gap-2 justify-end">
                                <LemonButton
                                    data-attr="cancel-feature-flag"
                                    type="secondary"
                                    onClick={() => {
                                        if (isEditingFlag) {
                                            editFeatureFlag(false)
                                            loadFeatureFlag()
                                        } else {
                                            router.actions.push(urls.featureFlags())
                                        }
                                    }}
                                    disabled={featureFlagLoading}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    data-attr="save-feature-flag"
                                    htmlType="submit"
                                    loading={featureFlagLoading}
                                    disabled={featureFlagLoading}
                                >
                                    Save
                                </LemonButton>
                            </div>
                        </Form>
                    ) : (
                        <>
                            {featureFlagLoading ? (
                                <Skeleton active />
                            ) : (
                                <>
                                    <PageHeader
                                        title={
                                            <div className="flex items-center gap-2 mb-2">
                                                {featureFlag.key || 'Untitled'}
                                                <CopyToClipboardInline
                                                    explicitValue={featureFlag.key}
                                                    iconStyle={{ color: 'var(--muted-alt)' }}
                                                />
                                                <div className="flex">
                                                    {featureFlag.active ? (
                                                        <LemonTag type="success">Enabled</LemonTag>
                                                    ) : (
                                                        <LemonTag type="default">Disabled</LemonTag>
                                                    )}
                                                </div>
                                            </div>
                                        }
                                        description={
                                            <>
                                                {featureFlag.name ? (
                                                    <span style={{ fontStyle: 'normal' }}>{featureFlag.name}</span>
                                                ) : (
                                                    'There is no description for this feature flag.'
                                                )}
                                            </>
                                        }
                                        buttons={
                                            <div className="flex items-center gap-2 mb-2">
                                                <LemonButton
                                                    data-attr="delete-feature-flag"
                                                    status="danger"
                                                    type="secondary"
                                                    onClick={() => {
                                                        deleteFeatureFlag(featureFlag)
                                                    }}
                                                    disabled={featureFlagLoading}
                                                >
                                                    Delete feature flag
                                                </LemonButton>
                                                <LemonButton
                                                    data-attr="edit-feature-flag"
                                                    type="secondary"
                                                    onClick={() => {
                                                        editFeatureFlag(true)
                                                    }}
                                                    disabled={featureFlagLoading}
                                                >
                                                    Edit
                                                </LemonButton>
                                            </div>
                                        }
                                    />
                                    <Tabs
                                        activeKey={activeTab}
                                        destroyInactiveTabPane
                                        onChange={(t) => setActiveTab(t as FeatureFlagsTabs)}
                                    >
                                        <Tabs.TabPane tab="Overview" key="overview">
                                            <Row>
                                                <Col span={13}>
                                                    <FeatureFlagRollout readOnly />
                                                    <FeatureFlagReleaseConditions readOnly />
                                                </Col>
                                                <Col span={11} className="pl-4">
                                                    <RecentFeatureFlagInsights />
                                                    <div className="my-4" />
                                                    <FeatureFlagInstructions
                                                        featureFlagKey={featureFlag.key || 'my-flag'}
                                                    />
                                                </Col>
                                            </Row>
                                        </Tabs.TabPane>
                                        {featureFlag.id && (
                                            <Tabs.TabPane tab="History" key="history">
                                                <ActivityLog
                                                    scope={ActivityScope.FEATURE_FLAG}
                                                    describer={flagActivityDescriber}
                                                    id={featureFlag.id}
                                                />
                                            </Tabs.TabPane>
                                        )}
                                    </Tabs>
                                </>
                            )}
                        </>
                    )}
                </div>
            ) : (
                <Form
                    logic={featureFlagLogic}
                    props={props}
                    formKey="featureFlag"
                    enableFormOnSubmit
                    className="space-y-4"
                >
                    <PageHeader
                        title="Feature Flag"
                        buttons={
                            <div className="flex items-center gap-2">
                                <Field name="active">
                                    {({ value, onChange }) => (
                                        <LemonSwitch
                                            data-attr="feature-flag-enabled-toggle"
                                            checked={value}
                                            onChange={onChange}
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
                                    <LemonButton
                                        data-attr="delete-flag"
                                        status="danger"
                                        type="secondary"
                                        onClick={() => {
                                            deleteFeatureFlag(featureFlag)
                                        }}
                                    >
                                        Delete
                                    </LemonButton>
                                )}
                                <LemonButton
                                    type="primary"
                                    data-attr="feature-flag-submit"
                                    loading={featureFlagLoading}
                                    htmlType="submit"
                                >
                                    Save changes
                                </LemonButton>
                            </div>
                        }
                    />
                    {featureFlag.experiment_set && featureFlag.experiment_set?.length > 0 && (
                        <AlertMessage type="warning">
                            This feature flag is linked to an experiment. It's recommended to only make changes to this
                            flag{' '}
                            <Link to={urls.experiment(featureFlag.experiment_set[0])}>
                                using the experiment creation screen.
                            </Link>
                        </AlertMessage>
                    )}
                    <EventBufferNotice additionalInfo=", meaning it can take around 60 seconds for some flags to update for recently-identified persons" />
                    <h3 className="l3 mt-4">General configuration</h3>
                    <div className="text-muted mb-4">
                        General settings for your feature flag and integration instructions.
                    </div>
                    <Row gutter={16} style={{ marginBottom: 32 }}>
                        <Col span={12} className="space-y-4">
                            <Field
                                name="key"
                                label="Key (must be unique)"
                                help={
                                    hasKeyChanged && id !== 'new' ? (
                                        <span className="text-warning">
                                            <b>Warning! </b>Changing this key will
                                            <a
                                                href={`https://posthog.com/docs/features/feature-flags${UTM_TAGS}#feature-flag-persistence`}
                                                target="_blank"
                                                rel="noopener"
                                            >
                                                {' '}
                                                affect the persistence of your flag <IconOpenInNew />
                                            </a>
                                        </span>
                                    ) : undefined
                                }
                            >
                                {({ value, onChange }) => (
                                    <LemonInput
                                        value={value}
                                        onChange={(v) => {
                                            if (v !== value) {
                                                setHasKeyChanged(true)
                                            }
                                            onChange(v)
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
                                <LemonTextArea
                                    className="ph-ignore-input"
                                    data-attr="feature-flag-description"
                                    placeholder="Adding a helpful description can ensure others know what this feature is for."
                                />
                            </Field>
                            <Field name="ensure_experience_continuity">
                                {({ value, onChange }) => (
                                    <div className="border rounded p-4">
                                        <LemonCheckbox
                                            id="continuity-checkbox"
                                            label="Persist flag across authentication steps"
                                            onChange={() => onChange(!value)}
                                            fullWidth
                                            checked={value}
                                        />
                                        <div className="text-muted text-sm pl-7">
                                            If your feature flag is applied prior to an identify or authentication
                                            event, use this to ensure that feature flags are not reset after a person is
                                            identified. This ensures the experience for the anonymous person is carried
                                            forward to the authenticated person.
                                        </div>
                                    </div>
                                )}
                            </Field>
                        </Col>
                        <Col span={12}>
                            <FeatureFlagInstructions featureFlagKey={featureFlag.key || 'my-flag'} />
                        </Col>
                    </Row>

                    <div className="mb-8">
                        <h3 className="l3">Served value</h3>
                        <div className="mb-2">
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
                        <div className="text-muted mb-4">
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
                            <div className="variant-form-list space-y-2">
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
                                                    <LemonInput
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
                                                    <LemonInput
                                                        data-attr="feature-flag-variant-name"
                                                        className="ph-ignore-input"
                                                        placeholder="Description"
                                                    />
                                                </Field>
                                            </Col>
                                            <Col span={7}>
                                                <Field name="rollout_percentage">
                                                    <Slider tooltipPlacement="top" />
                                                </Field>
                                            </Col>
                                            <Col span={2}>
                                                <Field name="rollout_percentage">
                                                    {({ value, onChange }) => (
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
                                                                        onChange(valueInt)
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
                                <LemonButton
                                    type="secondary"
                                    onClick={() => {
                                        const newIndex = variants.length
                                        addVariant()
                                        focusVariantKeyField(newIndex)
                                    }}
                                    fullWidth
                                    center
                                >
                                    Add variant
                                </LemonButton>
                            </div>
                        )}
                    </div>

                    <div className="feature-flag-form-row">
                        <div data-attr="feature-flag-release-conditions">
                            <h3 className="l3">Release conditions</h3>
                            <div className="text-muted mb-4">
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
                                        <div className="stateful-badge or-light-grey mb-4">OR</div>
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
                                                    size="small"
                                                    onClick={() => duplicateConditionSet(index)}
                                                />
                                            </Tooltip>
                                            {featureFlag.filters.groups.length > 1 && (
                                                <Tooltip title="Delete this condition set" placement="bottomLeft">
                                                    <LemonButton
                                                        icon={<IconDelete />}
                                                        size="small"
                                                        onClick={() => removeConditionSet(index)}
                                                    />
                                                </Tooltip>
                                            )}
                                        </Row>
                                    </div>

                                    <LemonDivider className="my-4" />
                                    <div className="ml-4">
                                        <PropertyFilters
                                            pageKey={`feature-flag-${featureFlag.id}-${index}-${
                                                featureFlag.filters.groups.length
                                            }-${featureFlag.filters.aggregation_group_type_index ?? ''}`}
                                            propertyFilters={group?.properties}
                                            onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                            taxonomicGroupTypes={taxonomicGroupTypes}
                                            showConditionBadge
                                        />
                                    </div>

                                    <LemonDivider className="my-4" />

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
                        <LemonButton onClick={addConditionSet} fullWidth>
                            Add condition set
                        </LemonButton>
                    </Card>
                    <div className="text-right">
                        <LemonButton
                            htmlType="submit"
                            loading={featureFlagLoading}
                            type="primary"
                            data-attr="feature-flag-submit-bottom"
                        >
                            Save changes
                        </LemonButton>
                    </div>
                </Form>
            )}
        </>
    )
}

interface FeatureFlagReadOnlyProps {
    readOnly?: boolean
}

function FeatureFlagRollout({ readOnly }: FeatureFlagReadOnlyProps): JSX.Element {
    const {
        multivariateEnabled,
        variants,
        areVariantRolloutsValid,
        featureFlagLoading,
        variantRolloutSum,
        nonEmptyVariants,
        aggregationTargetName,
        featureFlag,
    } = useValues(featureFlagLogic)
    const { distributeVariantsEqually, addVariant, removeVariant, setMultivariateEnabled } =
        useActions(featureFlagLogic)
    const [showVariantDiscardWarning, setShowVariantDiscardWarning] = useState(false)
    const { hasAvailableFeature, upgradeLink } = useValues(userLogic)

    return (
        <>
            {readOnly ? (
                <>
                    <div className="font-medium border rounded p-2 pl-3 mb-4">
                        Served value:{' '}
                        <b>
                            {featureFlag.filters.multivariate
                                ? 'Multiple variants with rollout percentages (A/B test)'
                                : 'Release toggle (boolean)'}
                        </b>
                    </div>
                    {featureFlag.filters.multivariate && (
                        <>
                            <div className="mb-2">
                                <b>Variant keys</b>
                            </div>
                            <div className="border rounded p-4 mb-4">
                                <Row className="font-semibold">
                                    <Col span={10}>Key</Col>
                                    <Col span={11}>Description</Col>
                                    <Col span={3}>Rollout</Col>
                                </Row>
                                <LemonDivider className="my-3" />
                                {variants.map((variant, index) => (
                                    <>
                                        <Row>
                                            <Col span={10}>
                                                <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                                <CopyToClipboardInline
                                                    tooltipMessage={null}
                                                    description="key"
                                                    style={{
                                                        marginLeft: '0.5rem',
                                                    }}
                                                    iconStyle={{ color: 'var(--muted-alt)' }}
                                                >
                                                    {variant.key}
                                                </CopyToClipboardInline>
                                            </Col>
                                            <Col span={12}>
                                                {variant.name || 'There is no description for this variant key'}
                                            </Col>
                                            <Col span={2}>{variant.rollout_percentage}%</Col>
                                        </Row>
                                        {index !== variants.length - 1 && <LemonDivider className="my-3" />}
                                    </>
                                ))}
                            </div>
                        </>
                    )}
                </>
            ) : (
                <div className="mb-8">
                    <h3 className="l4">Served value</h3>
                    <div className="mb-2">
                        <Popconfirm
                            placement="top"
                            title="Change value type? The variants below will be lost."
                            disabled={featureFlagLoading}
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
                                        label: 'Release toggle (boolean)',
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
                                                    Multiple variants with rollout percentages (A/B test)
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
                    <div className="text-muted mb-4">
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
                </div>
            )}
            {!readOnly && multivariateEnabled && (
                <div className="feature-flag-variants">
                    <h3 className="l4">Variant keys</h3>
                    <span>The rollout percentage of feature flag variants must add up to 100%</span>
                    <div className="variant-form-list space-y-2">
                        <Row gutter={8} className="label-row">
                            <Col span={1} />
                            <Col span={6}>Variant key</Col>
                            <Col span={12}>Description</Col>
                            <Col span={4}>
                                Rollout
                                <LemonButton type="tertiary" onClick={distributeVariantsEqually}>
                                    (Redistribute)
                                </LemonButton>
                            </Col>
                        </Row>
                        {variants.map((_, index) => (
                            <Group key={index} name={['filters', 'multivariate', 'variants', index]}>
                                <Row gutter={8} align="middle">
                                    <Col span={1}>
                                        <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                    </Col>
                                    <Col span={6}>
                                        <Field name="key">
                                            <LemonInput
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
                                    <Col span={12}>
                                        <Field name="name">
                                            <LemonInput
                                                data-attr="feature-flag-variant-name"
                                                className="ph-ignore-input"
                                                placeholder="Description"
                                            />
                                        </Field>
                                    </Col>
                                    <Col span={3}>
                                        <Field name="rollout_percentage">
                                            {({ value, onChange }) => (
                                                <InputNumber
                                                    min={0}
                                                    max={100}
                                                    value={value}
                                                    onChange={(changedValue) => {
                                                        if (changedValue !== null && changedValue !== undefined) {
                                                            const valueInt = parseInt(changedValue.toString())
                                                            if (!isNaN(valueInt)) {
                                                                onChange(valueInt)
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
                                    <Col span={2}>
                                        <Row>
                                            {variants.length > 1 && (
                                                <LemonButton
                                                    icon={<IconDelete />}
                                                    status="primary-alt"
                                                    data-attr={`delete-prop-filter-${index}`}
                                                    noPadding
                                                    onClick={() => removeVariant(index)}
                                                />
                                            )}
                                        </Row>
                                    </Col>
                                </Row>
                            </Group>
                        ))}
                        {variants.length > 0 && !areVariantRolloutsValid && (
                            <p className="text-danger">
                                Percentage rollouts for variants must sum to 100 (currently {variantRolloutSum}
                                ).
                            </p>
                        )}
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                const newIndex = variants.length
                                addVariant()
                                focusVariantKeyField(newIndex)
                            }}
                            icon={<IconPlus />}
                            center
                        >
                            Add variant
                        </LemonButton>
                    </div>
                </div>
            )}
        </>
    )
}

function FeatureFlagReleaseConditions({ readOnly }: FeatureFlagReadOnlyProps): JSX.Element {
    const { showGroupsOptions, aggregationLabel } = useValues(groupsModel)
    const { aggregationTargetName, featureFlag, groupTypes, taxonomicGroupTypes } = useValues(featureFlagLogic)
    const {
        setAggregationGroupTypeIndex,
        updateConditionSet,
        duplicateConditionSet,
        removeConditionSet,
        addConditionSet,
    } = useActions(featureFlagLogic)
    const { cohortsById } = useValues(cohortsModel)

    // :KLUDGE: Match by select only allows Select.Option as children, so render groups option directly rather than as a child
    const matchByGroupsIntroductionOption = GroupsIntroductionOption({ value: -2 })
    const instantProperties = [
        '$geoip_city_name',
        '$geoip_country_name',
        '$geoip_country_code',
        '$geoip_continent_name',
        '$geoip_continent_code',
        '$geoip_postal_code',
        '$geoip_time_zone',
    ]
    const hasNonInstantProperty = (properties: AnyPropertyFilter[]): boolean => {
        return !!properties.find(
            (property) => property.type === 'cohort' || !instantProperties.includes(property.key || '')
        )
    }
    return (
        <>
            <div className="feature-flag-form-row">
                <div data-attr="feature-flag-release-conditions">
                    {readOnly ? (
                        <div className="mb-2">
                            <b>Release conditions</b>
                        </div>
                    ) : (
                        <>
                            <h3 className="l4">Release conditions</h3>
                            <div className="text-muted mb-4">
                                Specify the {aggregationTargetName} to which you want to release this flag. Note that
                                condition sets are rolled out independently of each other.
                            </div>
                        </>
                    )}
                </div>
                {!readOnly && showGroupsOptions && (
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
                                <Select.Option key={groupType.group_type_index} value={groupType.group_type_index}>
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
                        {index > 0 && <div className="condition-set-separator">OR</div>}
                        <div className="mb-4 border rounded p-4">
                            <Row align="middle" justify="space-between">
                                <Row align="middle">
                                    <span className="simple-tag tag-light-blue font-medium mr-2">Set {index + 1}</span>
                                    <div>
                                        {group.properties?.length ? (
                                            <>
                                                {readOnly ? (
                                                    <>
                                                        Match <b>{aggregationTargetName}</b> against <b>all</b> criteria
                                                    </>
                                                ) : (
                                                    <>
                                                        Matching <b>{aggregationTargetName}</b> against the criteria
                                                    </>
                                                )}
                                            </>
                                        ) : (
                                            <>
                                                Condition set will match <b>all {aggregationTargetName}</b>
                                            </>
                                        )}
                                    </div>
                                </Row>
                                {!readOnly && (
                                    <Row>
                                        <LemonButton
                                            icon={<IconCopy />}
                                            status="muted"
                                            noPadding
                                            onClick={() => duplicateConditionSet(index)}
                                        />
                                        {featureFlag.filters.groups.length > 1 && (
                                            <LemonButton
                                                icon={<IconDelete />}
                                                status="muted"
                                                noPadding
                                                onClick={() => removeConditionSet(index)}
                                            />
                                        )}
                                    </Row>
                                )}
                            </Row>
                            <LemonDivider className="my-3" />
                            {!readOnly && hasNonInstantProperty(group.properties) && (
                                <AlertMessage type="info" className="mt-3 mb-3">
                                    These properties aren't immediately available on first page load for unidentified
                                    persons. This feature flag requires that at least one event is sent prior to
                                    becoming available to your product or website.{' '}
                                    <a
                                        href="https://posthog.com/docs/integrate/client/js#bootstrapping-flags"
                                        target="_blank"
                                    >
                                        {' '}
                                        Learn more about how to make feature flags available instantly.
                                    </a>
                                </AlertMessage>
                            )}

                            {readOnly ? (
                                <>
                                    {group.properties.map((property, idx) => (
                                        <>
                                            <div className="feature-flag-property-display">
                                                {idx === 0 ? (
                                                    <LemonButton
                                                        icon={<IconSubArrowRight className="arrow-right" />}
                                                        status="muted"
                                                        size="small"
                                                    />
                                                ) : (
                                                    <LemonButton
                                                        icon={<span className="text-sm">&</span>}
                                                        status="muted"
                                                        size="small"
                                                    />
                                                )}
                                                <span className="simple-tag tag-light-blue text-primary-alt">
                                                    {property.type === 'cohort' ? 'Cohort' : property.key}{' '}
                                                </span>
                                                <span>{allOperatorsToHumanName(property.operator)} </span>
                                                {[
                                                    ...(Array.isArray(property.value)
                                                        ? property.value
                                                        : [property.value]),
                                                ].map((val, idx) => (
                                                    <span
                                                        key={idx}
                                                        className="simple-tag tag-light-blue text-primary-alt"
                                                    >
                                                        {property.type === 'cohort'
                                                            ? (val && cohortsById[val]?.name) || `ID ${val}`
                                                            : val}
                                                    </span>
                                                ))}
                                            </div>
                                        </>
                                    ))}
                                </>
                            ) : (
                                <div>
                                    <PropertyFilters
                                        orFiltering={true}
                                        pageKey={`feature-flag-${featureFlag.id}-${index}-${
                                            featureFlag.filters.groups.length
                                        }-${featureFlag.filters.aggregation_group_type_index ?? ''}`}
                                        propertyFilters={group?.properties}
                                        logicalRowDivider
                                        addButton={
                                            <LemonButton icon={<IconPlusMini />} noPadding>
                                                Add condition
                                            </LemonButton>
                                        }
                                        onChange={(properties) => updateConditionSet(index, undefined, properties)}
                                        taxonomicGroupTypes={taxonomicGroupTypes}
                                        hasRowOperator={false}
                                    />
                                </div>
                            )}
                            {(!readOnly || (readOnly && group.properties?.length > 0)) && (
                                <LemonDivider className="my-3" />
                            )}
                            {readOnly ? (
                                <div>
                                    Rolled out to{' '}
                                    <b>{group.rollout_percentage != null ? group.rollout_percentage : 100}%</b> of{' '}
                                    <b>{aggregationTargetName}</b> in this set
                                </div>
                            ) : (
                                <div className="feature-flag-form-row">
                                    <div className="centered">
                                        Roll out to{' '}
                                        <InputNumber
                                            style={{ width: 100, marginLeft: 8, marginRight: 8 }}
                                            onChange={(value): void => {
                                                updateConditionSet(index, value as number)
                                            }}
                                            value={group.rollout_percentage != null ? group.rollout_percentage : 100}
                                            min={0}
                                            max={100}
                                            addonAfter="%"
                                        />{' '}
                                        of <b>{aggregationTargetName}</b> in this set
                                    </div>
                                </div>
                            )}
                        </div>
                    </Col>
                ))}
            </Row>
            {!readOnly && (
                <LemonButton type="secondary" className="mt-0" onClick={addConditionSet} icon={<IconPlus />}>
                    Add condition set
                </LemonButton>
            )}
        </>
    )
}
