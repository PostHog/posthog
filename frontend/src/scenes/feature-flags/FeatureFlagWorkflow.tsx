import './FeatureFlag.scss'

import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { groupsModel } from 'models/groupsModel'
import { useState } from 'react'

import {
    IconCode,
    IconDevices,
    IconGlobe,
    IconInfo,
    IconList,
    IconPerson,
    IconPlus,
    IconServer,
    IconToggle,
    IconTrash,
} from '@posthog/icons'
import {
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSelect,
    LemonSwitch,
    LemonTextArea,
    Lettermark,
    LettermarkColor,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import 'lib/lemon-ui/Lettermark'
import { alphabet } from 'lib/utils'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AnyPropertyFilter, FeatureFlagEvaluationRuntime, FeatureFlagGroupType } from '~/types'

import { FeatureFlagCodeExample } from './FeatureFlagCodeExample'
import { FeatureFlagTemplates } from './FeatureFlagTemplates'
import { FeatureFlagLogicProps, featureFlagLogic } from './featureFlagLogic'

export function FeatureFlagWorkflow({ id }: FeatureFlagLogicProps): JSX.Element {
    const { props, featureFlag, multivariateEnabled, variants, nonEmptyVariants, variantErrors } =
        useValues(featureFlagLogic)
    const {
        setMultivariateEnabled,
        setFeatureFlag,
        addVariant,
        removeVariant,
        updateVariant,
        distributeVariantsEqually,
        setFeatureFlagFilters,
    } = useActions(featureFlagLogic)
    const { groupTypes, aggregationLabel } = useValues(groupsModel)

    const [showImplementation, setShowImplementation] = useState(false)
    const [openConditions, setOpenConditions] = useState<string[]>([])
    const [openVariants, setOpenVariants] = useState<string[]>([])

    const isNewFeatureFlag = id === 'new' || id === undefined
    const groups = featureFlag?.filters?.groups || []

    return (
        <>
            <Form
                id="feature-flag"
                logic={featureFlagLogic}
                props={props}
                formKey="featureFlag"
                enableFormOnSubmit
                className="deprecated-space-y-4"
            >
                <SceneTitleSection
                    name={featureFlag.key || 'New feature flag'}
                    resourceType={{
                        type: featureFlag.active ? 'feature_flag' : 'feature_flag_off',
                    }}
                    actions={
                        <>
                            <LemonButton
                                data-attr="cancel-feature-flag"
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    router.actions.push(urls.featureFlags())
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                data-attr="save-feature-flag"
                                htmlType="submit"
                                form="feature-flag"
                                size="small"
                            >
                                Save
                            </LemonButton>
                        </>
                    }
                />

                <SceneContent>
                    {/* Templates - only show for new flags */}
                    {isNewFeatureFlag && (
                        <FeatureFlagTemplates
                            onTemplateApplied={(sectionsToOpen) => {
                                // Open relevant condition sets when template is applied
                                if (sectionsToOpen.includes('targeting')) {
                                    setOpenConditions(['condition-0'])
                                }
                            }}
                        />
                    )}

                    {/* Two-column layout */}
                    <div className="flex gap-4 mt-4 flex-wrap">
                        {/* Left column - narrow */}
                        <div className="flex-1 min-w-[20rem] flex flex-col gap-4">
                            {/* Main settings card */}
                            <div className="rounded border p-3 bg-white gap-2 flex flex-col">
                                <LemonField name="key">
                                    <LemonLabel info="The key is used to identify the feature flag in the code. Must be unique.">
                                        Flag key
                                    </LemonLabel>
                                    <LemonInput
                                        data-attr="feature-flag-key"
                                        className="ph-ignore-input"
                                        autoComplete="off"
                                        autoCapitalize="off"
                                        autoCorrect="off"
                                        spellCheck={false}
                                        placeholder="Enter a unique key - e.g. new-landing-page, betaFeature, ab_test_1"
                                    />
                                </LemonField>

                                <LemonField name="name">
                                    <LemonLabel>Description</LemonLabel>
                                    <LemonTextArea
                                        className="ph-ignore-input"
                                        data-attr="feature-flag-description"
                                        placeholder="(Optional) A description of the feature flag for your reference."
                                    />
                                </LemonField>

                                <LemonDivider />

                                <LemonField name="active">
                                    <Tooltip
                                        title="When enabled, this flag evaluates according to your release conditions. When disabled, this flag will not be evaluated and PostHog SDKs default to returning false."
                                        placement="right"
                                    >
                                        <LemonSwitch
                                            label={
                                                <span className="flex items-center">
                                                    <span>Enabled</span>
                                                    <IconInfo className="ml-1 text-lg" />
                                                </span>
                                            }
                                            bordered
                                            fullWidth
                                            data-attr="feature-flag-enabled"
                                        />
                                    </Tooltip>
                                </LemonField>

                                <LemonField name="ensure_experience_continuity">
                                    <Tooltip
                                        title={
                                            <>
                                                If your feature flag is applied before identifying the user, use this to
                                                ensure that the flag value remains consistent for the same user.
                                                Depending on your setup, this option might not always be suitable. This
                                                feature requires creating profiles for anonymous users.{' '}
                                                <Link
                                                    to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                                                    target="_blank"
                                                >
                                                    Learn more
                                                </Link>
                                            </>
                                        }
                                        placement="right"
                                    >
                                        <LemonSwitch
                                            bordered
                                            fullWidth
                                            label={
                                                <span className="flex items-center">
                                                    <span>Persist flag across authentication steps</span>
                                                    <IconInfo className="ml-1 text-lg" />
                                                </span>
                                            }
                                            data-attr="feature-flag-persist-across-auth"
                                        />
                                    </Tooltip>
                                </LemonField>
                            </div>

                            {/* Advanced options card */}
                            <div className="rounded border p-3 bg-white gap-2 flex flex-col">
                                <LemonLabel>Advanced options</LemonLabel>

                                <LemonField name="evaluation_runtime">
                                    <LemonSelect
                                        fullWidth
                                        options={[
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Both client and server</span>
                                                        <span className="text-xs text-muted">
                                                            Single-user apps + multi-user systems
                                                        </span>
                                                    </div>
                                                ),
                                                value: FeatureFlagEvaluationRuntime.ALL,
                                                icon: <IconGlobe />,
                                            },
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Client-side only</span>
                                                        <span className="text-xs text-muted">
                                                            Single-user apps (mobile, desktop, embedded)
                                                        </span>
                                                    </div>
                                                ),
                                                value: FeatureFlagEvaluationRuntime.CLIENT,
                                                icon: <IconList />,
                                            },
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Server-side only</span>
                                                        <span className="text-xs text-muted">
                                                            Multi-user systems in trusted environments
                                                        </span>
                                                    </div>
                                                ),
                                                value: FeatureFlagEvaluationRuntime.SERVER,
                                                icon: <IconServer />,
                                            },
                                        ]}
                                        data-attr="feature-flag-evaluation-runtime"
                                    />
                                </LemonField>
                            </div>
                        </div>

                        {/* Right column - wide */}
                        <div className="flex-2 flex flex-col gap-4" style={{ minWidth: '30rem' }}>
                            {/* Flag type card */}
                            <div className="rounded border p-3 bg-white gap-4 flex flex-col">
                                <div className="flex flex-col gap-2">
                                    <LemonLabel>Flag type</LemonLabel>
                                    <LemonSelect
                                        fullWidth
                                        value={
                                            featureFlag.is_remote_configuration
                                                ? 'remote_config'
                                                : multivariateEnabled
                                                  ? 'multivariate'
                                                  : 'boolean'
                                        }
                                        onChange={(value) => {
                                            if (value === 'remote_config') {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    is_remote_configuration: true,
                                                })
                                                setMultivariateEnabled(false)
                                            } else if (value === 'multivariate') {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    is_remote_configuration: false,
                                                })
                                                setMultivariateEnabled(true)
                                            } else {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    is_remote_configuration: false,
                                                })
                                                setMultivariateEnabled(false)
                                            }
                                        }}
                                        options={[
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Boolean</span>
                                                        <span className="text-xs text-muted">
                                                            Release toggle (boolean) with optional static payload
                                                        </span>
                                                    </div>
                                                ),
                                                value: 'boolean',
                                                icon: <IconToggle />,
                                            },
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Multivariate</span>
                                                        <span className="text-xs text-muted">
                                                            Multiple variants with rollout percentages (A/B/n test)
                                                        </span>
                                                    </div>
                                                ),
                                                value: 'multivariate',
                                                icon: <IconList />,
                                            },
                                            {
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Remote config</span>
                                                        <span className="text-xs text-muted">
                                                            Single payload without feature flag logic
                                                        </span>
                                                    </div>
                                                ),
                                                value: 'remote_config',
                                                icon: <IconCode />,
                                            },
                                        ]}
                                        data-attr="feature-flag-type"
                                    />
                                </div>

                                {/* Variants section - only for multivariate */}
                                {multivariateEnabled && (
                                    <div className="flex flex-col gap-2">
                                        <div className="flex items-center justify-between">
                                            <LemonLabel>Variants</LemonLabel>
                                            <LemonButton size="small" onClick={distributeVariantsEqually}>
                                                Distribute equally
                                            </LemonButton>
                                        </div>

                                        <LemonCollapse
                                            multiple
                                            activeKeys={openVariants}
                                            onChange={setOpenVariants}
                                            panels={variants.map((variant, index) => ({
                                                key: `variant-${index}`,
                                                header: (
                                                    <div className="flex gap-2 items-center">
                                                        <Lettermark
                                                            name={alphabet[index]}
                                                            color={LettermarkColor.Gray}
                                                            size="small"
                                                        />
                                                        <span className="text-sm font-medium">
                                                            {variant.key || `Variant ${index + 1}`}
                                                        </span>
                                                        <span className="text-xs text-muted">
                                                            ({variant.rollout_percentage || 0}%)
                                                        </span>
                                                    </div>
                                                ),
                                                content: (
                                                    <div className="flex flex-col gap-2">
                                                        <LemonLabel>Variant key</LemonLabel>
                                                        <LemonInput
                                                            placeholder="Enter a variant key - e.g. control, test, variant_1"
                                                            value={variant.key}
                                                            onChange={(value) => updateVariant(index, 'key', value)}
                                                            status={variantErrors[index]?.key ? 'danger' : undefined}
                                                            data-attr={`feature-flag-variant-key-${index}`}
                                                        />
                                                        {variantErrors[index]?.key && (
                                                            <span className="text-danger text-xs">
                                                                {variantErrors[index].key}
                                                            </span>
                                                        )}

                                                        <LemonLabel>Rollout percentage</LemonLabel>
                                                        <LemonInput
                                                            type="number"
                                                            min={0}
                                                            max={100}
                                                            value={variant.rollout_percentage || 0}
                                                            onChange={(value) =>
                                                                updateVariant(
                                                                    index,
                                                                    'rollout_percentage',
                                                                    parseInt(value?.toString() || '0')
                                                                )
                                                            }
                                                            suffix={<span>%</span>}
                                                            data-attr={`feature-flag-variant-rollout-${index}`}
                                                        />

                                                        {/* Show effective percentage if there are release conditions with rollout */}
                                                        {(() => {
                                                            const groups = featureFlag?.filters?.groups || []
                                                            const releaseConditionsWithRollout = groups.filter(
                                                                (group) =>
                                                                    !group.variant &&
                                                                    (group.rollout_percentage ?? 100) < 100
                                                            )

                                                            if (releaseConditionsWithRollout.length > 0) {
                                                                const minRollout = Math.min(
                                                                    ...releaseConditionsWithRollout.map(
                                                                        (g) => g.rollout_percentage ?? 100
                                                                    )
                                                                )
                                                                const variantRollout = variant.rollout_percentage || 0
                                                                const effectiveRollout =
                                                                    (minRollout * variantRollout) / 100

                                                                return (
                                                                    <div className="text-xs mt-1 text-secondary">
                                                                        Effective: ~{effectiveRollout.toFixed(1)}% of
                                                                        all users
                                                                        <div className="text-muted">
                                                                            ({variantRollout}% of {minRollout}% eligible
                                                                            users)
                                                                        </div>
                                                                    </div>
                                                                )
                                                            }
                                                            return null
                                                        })()}

                                                        <LemonLabel>Description</LemonLabel>
                                                        <LemonTextArea
                                                            placeholder="Enter a description for the variant"
                                                            value={variant.name || ''}
                                                            onChange={(value) => updateVariant(index, 'name', value)}
                                                            data-attr={`feature-flag-variant-description-${index}`}
                                                        />

                                                        {variants.length > 1 && (
                                                            <LemonButton
                                                                type="secondary"
                                                                status="danger"
                                                                size="small"
                                                                icon={<IconTrash />}
                                                                onClick={() => removeVariant(index)}
                                                            >
                                                                Remove variant
                                                            </LemonButton>
                                                        )}
                                                    </div>
                                                ),
                                            }))}
                                        />

                                        <div>
                                            <LemonButton
                                                type="secondary"
                                                icon={<IconPlus />}
                                                onClick={addVariant}
                                                data-attr="feature-flag-add-variant"
                                            >
                                                Add variant
                                            </LemonButton>
                                        </div>
                                    </div>
                                )}
                            </div>

                            {/* Release conditions card - skip for remote config */}
                            {!featureFlag.is_remote_configuration && (
                                <div className="rounded border p-3 bg-white gap-2 flex flex-col">
                                    <LemonLabel>Release conditions</LemonLabel>
                                    <p className="text-sm text-muted">
                                        Condition sets are evaluated top to bottom - the first matching set is used. A
                                        condition matches when all property filters pass AND the target falls within the
                                        rollout percentage.
                                    </p>

                                    {/* Bucketing identifier selector */}
                                    <LemonSelect
                                        fullWidth
                                        value={
                                            featureFlag.filters?.aggregation_group_type_index != null
                                                ? `group_${featureFlag.filters.aggregation_group_type_index}`
                                                : featureFlag.bucketing_identifier === 'distinct_id'
                                                  ? 'device_id'
                                                  : 'distinct_id'
                                        }
                                        onChange={(value) => {
                                            if (value.startsWith('group_')) {
                                                const groupTypeIndex = parseInt(value.replace('group_', ''))
                                                setFeatureFlagFilters({
                                                    ...featureFlag.filters,
                                                    aggregation_group_type_index: groupTypeIndex,
                                                    groups: [
                                                        {
                                                            properties: [],
                                                            rollout_percentage: 100,
                                                            variant: null,
                                                        },
                                                    ],
                                                })
                                            } else if (value === 'device_id') {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    bucketing_identifier: 'distinct_id',
                                                    filters: {
                                                        ...featureFlag.filters,
                                                        aggregation_group_type_index: null,
                                                    },
                                                })
                                            } else {
                                                setFeatureFlag({
                                                    ...featureFlag,
                                                    bucketing_identifier: null,
                                                    filters: {
                                                        ...featureFlag.filters,
                                                        aggregation_group_type_index: null,
                                                    },
                                                })
                                            }
                                        }}
                                        options={[
                                            {
                                                value: 'distinct_id',
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Match by distinct ID</span>
                                                        <span className="text-xs text-muted">
                                                            Stable assignment for logged-in users based on their unique
                                                            user ID.
                                                        </span>
                                                    </div>
                                                ),
                                                icon: <IconPerson />,
                                            },
                                            {
                                                value: 'device_id',
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">Device ID</span>
                                                        <span className="text-xs text-muted">
                                                            Stable assignment per device. Good fit for experiments on
                                                            anonymous users.
                                                        </span>
                                                    </div>
                                                ),
                                                icon: <IconDevices />,
                                            },
                                            ...Array.from(groupTypes.values()).map((groupType) => ({
                                                value: `group_${groupType.group_type_index}`,
                                                label: (
                                                    <div className="flex flex-col">
                                                        <span className="font-medium">
                                                            {aggregationLabel(groupType.group_type_index).singular}
                                                        </span>
                                                        <span className="text-xs text-muted">
                                                            Stable assignment for everyone in a{' '}
                                                            {aggregationLabel(
                                                                groupType.group_type_index
                                                            ).singular.toLowerCase()}
                                                            .
                                                        </span>
                                                    </div>
                                                ),
                                                icon: <IconList />,
                                            })),
                                        ]}
                                        data-attr="feature-flag-aggregation-type"
                                    />

                                    {/* Condition sets */}
                                    <LemonCollapse
                                        multiple
                                        activeKeys={openConditions}
                                        onChange={setOpenConditions}
                                        panels={groups.map((group: FeatureFlagGroupType, index: number) => {
                                            const hasProperties = group.properties && group.properties.length > 0
                                            const propertyCount = group.properties?.length || 0
                                            const rollout = group.rollout_percentage ?? 100

                                            return {
                                                key: `condition-${index}`,
                                                header: (
                                                    <div className="flex gap-2 items-center flex-1">
                                                        <Lettermark
                                                            name={String(index + 1)}
                                                            color={LettermarkColor.Gray}
                                                            size="small"
                                                        />
                                                        <span className="text-sm font-medium mr-2">
                                                            Condition {index + 1}
                                                        </span>
                                                        {hasProperties && (
                                                            <code className="text-xs text-muted rounded px-1 py-0.5">
                                                                {propertyCount}{' '}
                                                                {propertyCount === 1 ? 'filter' : 'filters'}
                                                            </code>
                                                        )}
                                                        <span className="flex-1" />
                                                        <span className="text-xs text-muted">{rollout}%</span>
                                                    </div>
                                                ),
                                                content: (
                                                    <div className="flex flex-col gap-2">
                                                        <LemonLabel>Match filters</LemonLabel>
                                                        <PropertyFilters
                                                            propertyFilters={group.properties || []}
                                                            onChange={(properties) => {
                                                                const newGroups = [...groups]
                                                                newGroups[index] = {
                                                                    ...newGroups[index],
                                                                    properties: properties as AnyPropertyFilter[],
                                                                }
                                                                setFeatureFlagFilters({
                                                                    ...featureFlag.filters,
                                                                    groups: newGroups,
                                                                })
                                                            }}
                                                            pageKey={`feature-flag-${featureFlag.id}-${index}`}
                                                            taxonomicGroupTypes={[]}
                                                            disabledReason={undefined}
                                                        />

                                                        <LemonLabel>Rollout percentage</LemonLabel>
                                                        <div className="flex items-center gap-2">
                                                            <LemonSlider
                                                                className="flex-1"
                                                                value={rollout}
                                                                min={0}
                                                                max={100}
                                                                step={1}
                                                                onChange={(value) => {
                                                                    const newGroups = [...groups]
                                                                    newGroups[index] = {
                                                                        ...newGroups[index],
                                                                        rollout_percentage: value,
                                                                    }
                                                                    setFeatureFlagFilters({
                                                                        ...featureFlag.filters,
                                                                        groups: newGroups,
                                                                    })
                                                                }}
                                                            />
                                                            <LemonInput
                                                                type="number"
                                                                min={0}
                                                                max={100}
                                                                value={rollout}
                                                                onChange={(value) => {
                                                                    const newGroups = [...groups]
                                                                    newGroups[index] = {
                                                                        ...newGroups[index],
                                                                        rollout_percentage: parseInt(
                                                                            value?.toString() || '100'
                                                                        ),
                                                                    }
                                                                    setFeatureFlagFilters({
                                                                        ...featureFlag.filters,
                                                                        groups: newGroups,
                                                                    })
                                                                }}
                                                                className="w-20"
                                                                suffix={<span>%</span>}
                                                            />
                                                        </div>

                                                        {/* Variant override for multivariate flags */}
                                                        {multivariateEnabled && nonEmptyVariants.length > 0 && (
                                                            <>
                                                                <LemonLabel>Override variant (optional)</LemonLabel>
                                                                <LemonSelect
                                                                    fullWidth
                                                                    allowClear
                                                                    placeholder="No override - use variant percentages"
                                                                    value={group.variant || null}
                                                                    onChange={(value) => {
                                                                        const newGroups = [...groups]
                                                                        newGroups[index] = {
                                                                            ...newGroups[index],
                                                                            variant: value,
                                                                        }
                                                                        setFeatureFlagFilters({
                                                                            ...featureFlag.filters,
                                                                            groups: newGroups,
                                                                        })
                                                                    }}
                                                                    options={nonEmptyVariants.map(
                                                                        (variant, vIndex) => ({
                                                                            value: variant.key,
                                                                            label: (
                                                                                <div className="flex items-center gap-2">
                                                                                    <Lettermark
                                                                                        name={alphabet[vIndex]}
                                                                                        color={LettermarkColor.Gray}
                                                                                        size="xsmall"
                                                                                    />
                                                                                    <span>{variant.key}</span>
                                                                                </div>
                                                                            ),
                                                                        })
                                                                    )}
                                                                />
                                                            </>
                                                        )}

                                                        <LemonDivider />

                                                        <LemonButton
                                                            type="secondary"
                                                            status="danger"
                                                            size="small"
                                                            icon={<IconTrash />}
                                                            onClick={() => {
                                                                const newGroups = groups.filter((_, i) => i !== index)
                                                                setFeatureFlagFilters({
                                                                    ...featureFlag.filters,
                                                                    groups:
                                                                        newGroups.length > 0
                                                                            ? newGroups
                                                                            : [
                                                                                  {
                                                                                      properties: [],
                                                                                      rollout_percentage: 100,
                                                                                      variant: null,
                                                                                  },
                                                                              ],
                                                                })
                                                                // Remove from open conditions
                                                                setOpenConditions(
                                                                    openConditions.filter(
                                                                        (k) => k !== `condition-${index}`
                                                                    )
                                                                )
                                                            }}
                                                        >
                                                            Remove condition
                                                        </LemonButton>
                                                    </div>
                                                ),
                                            }
                                        })}
                                    />

                                    <div>
                                        <LemonButton
                                            type="secondary"
                                            icon={<IconPlus />}
                                            onClick={() => {
                                                const newGroups = [
                                                    ...groups,
                                                    {
                                                        properties: [],
                                                        rollout_percentage: 100,
                                                        variant: null,
                                                    },
                                                ]
                                                setFeatureFlagFilters({
                                                    ...featureFlag.filters,
                                                    groups: newGroups,
                                                })
                                                // Open the new condition
                                                setOpenConditions([
                                                    ...openConditions,
                                                    `condition-${newGroups.length - 1}`,
                                                ])
                                            }}
                                            data-attr="feature-flag-add-condition"
                                        >
                                            Add condition
                                        </LemonButton>
                                    </div>
                                </div>
                            )}

                            {/* Implementation section */}
                            {showImplementation ? (
                                <div className="rounded border p-3 bg-white gap-2 flex flex-col">
                                    <LemonButton
                                        className="-m-2"
                                        icon={<IconCode />}
                                        onClick={() => setShowImplementation(false)}
                                    >
                                        Implementation
                                    </LemonButton>
                                    <LemonDivider />
                                    <FeatureFlagCodeExample featureFlag={featureFlag} />
                                </div>
                            ) : (
                                <div className="rounded border bg-bg-light gap-2 flex flex-col p-3">
                                    <LemonButton
                                        className="-m-2"
                                        icon={<IconCode />}
                                        onClick={() => setShowImplementation(true)}
                                    >
                                        Show implementation
                                    </LemonButton>
                                </div>
                            )}
                        </div>
                    </div>
                </SceneContent>
            </Form>
        </>
    )
}
