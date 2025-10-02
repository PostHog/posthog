import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { useState } from 'react'

import { IconInfo, IconLock, IconPlusSmall, IconToggle, IconTrash, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonCheckbox,
    LemonInput,
    LemonModal,
    LemonTable,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { AccessControlAction, userHasAccess } from 'lib/components/AccessControlAction'
import { ExperimentVariantNumber } from 'lib/components/SeriesGlyph'
import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { GroupsAccessStatus, groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { FeatureFlagFiltersSection } from 'scenes/feature-flags/FeatureFlagFilters'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType, FeatureFlagType } from '~/types'

import { experimentLogic } from './experimentLogic'
import { featureFlagEligibleForExperiment } from './utils'

const ExperimentFormFields = (): JSX.Element => {
    const { formMode, experiment, groupTypes, aggregationLabel, hasPrimaryMetricSet, validExistingFeatureFlag } =
        useValues(experimentLogic)
    const { addVariant, removeVariant, setExperiment, submitExperiment, setExperimentType, validateFeatureFlag } =
        useActions(experimentLogic)
    const { webExperimentsAvailable, unavailableFeatureFlagKeys } = useValues(experimentsLogic)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)
    const { featureFlags } = useValues(enabledFeaturesLogic)

    const { reportExperimentFeatureFlagModalOpened, reportExperimentFeatureFlagSelected } = useActions(eventUsageLogic)

    const [showFeatureFlagSelector, setShowFeatureFlagSelector] = useState(false)

    return (
        <SceneContent>
            <SceneTitleSection
                name={experiment.name}
                description={null}
                resourceType={{
                    type: 'experiment',
                }}
                canEdit={userHasAccess(
                    AccessControlResourceType.Experiment,
                    AccessControlLevel.Editor,
                    experiment.user_access_level
                )}
                onNameChange={(name) => {
                    setExperiment({ name })
                }}
                forceEdit={formMode === 'create'}
            />
            <SceneDivider />

            {hasPrimaryMetricSet && formMode !== 'duplicate' && (
                <LemonBanner type="info" className="my-4">
                    Fill out the details below to create your experiment based off of the insight.
                </LemonBanner>
            )}
            {formMode === 'duplicate' && (
                <LemonBanner type="info" className="my-4">
                    We'll copy all settings, including metrics and exposure configuration, from the&nbsp;
                    <Link target="_blank" className="font-semibold items-center" to={urls.experiment(experiment.id)}>
                        original experiment
                        <IconOpenInNew fontSize="18" />
                    </Link>
                    .
                </LemonBanner>
            )}

            <SceneSection title="Feature flag key" description="Each experiment is backed by a feature flag.">
                <LemonField
                    name="feature_flag_key"
                    className="max-w-120"
                    help={
                        <div className="flex items-center justify-between">
                            <LemonButton
                                type="secondary"
                                size="xsmall"
                                onClick={() => {
                                    reportExperimentFeatureFlagModalOpened()
                                    setShowFeatureFlagSelector(true)
                                }}
                            >
                                <IconToggle className="mr-1" />
                                Link to existing feature flag
                            </LemonButton>
                        </div>
                    }
                >
                    <LemonInput
                        placeholder="pricing-page-conversion"
                        data-attr="experiment-feature-flag-key"
                        onFocus={() => {
                            // Auto-generate feature flag key from experiment name when focusing on empty field
                            if (!experiment.feature_flag_key && experiment.name) {
                                setExperiment({
                                    feature_flag_key: generateFeatureFlagKey(
                                        experiment.name,
                                        unavailableFeatureFlagKeys
                                    ),
                                })
                            }
                        }}
                    />
                </LemonField>
            </SceneSection>

            <SceneDivider />
            <SceneSection title="Hypothesis / Description" description="Add your hypothesis for this test">
                <LemonField name="description" className="max-w-120">
                    <LemonTextArea
                        placeholder="The goal of this experiment is ..."
                        data-attr="experiment-description"
                    />
                </LemonField>
            </SceneSection>

            <SceneDivider />

            <SelectExistingFeatureFlagModal
                isOpen={showFeatureFlagSelector}
                onClose={() => setShowFeatureFlagSelector(false)}
                onSelect={(flag) => {
                    reportExperimentFeatureFlagSelected(flag.key)
                    setExperiment({
                        feature_flag_key: flag.key,
                        parameters: {
                            ...experiment.parameters,
                            feature_flag_variants: flag.filters?.multivariate?.variants || [],
                        },
                    })
                    validateFeatureFlag(flag.key)
                    setShowFeatureFlagSelector(false)
                }}
            />
            {webExperimentsAvailable && (
                <>
                    <SceneSection
                        title="Experiment type"
                        description="Select your experiment setup, this cannot be changed once saved."
                        className="gap-y-0"
                    >
                        <LemonRadio
                            value={experiment.type}
                            className="flex flex-col gap-2 mt-4"
                            onChange={(type) => {
                                setExperimentType(type)
                            }}
                            options={[
                                {
                                    value: 'product',
                                    description: (
                                        <div className="text-xs text-secondary">
                                            Use custom code to manage how variants modify your product.
                                        </div>
                                    ),
                                    label: 'Product experiment',
                                },
                                {
                                    value: 'web',
                                    label: 'No-code web experiment',
                                    description: (
                                        <div className="text-xs text-secondary">
                                            Define variants on your website using the PostHog toolbar, no coding
                                            required.
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    </SceneSection>
                    <SceneDivider />
                </>
            )}
            {groupsAccessStatus === GroupsAccessStatus.AlreadyUsing && (
                <>
                    <SceneSection
                        title="Participant type"
                        description="Determines on what level you want to aggregate metrics. You can change this later, but flag values for users will change so you need to reset the experiment for accurate results."
                        className="gap-y-0"
                    >
                        <LemonRadio
                            className="mt-4"
                            value={
                                experiment.parameters.aggregation_group_type_index != undefined
                                    ? experiment.parameters.aggregation_group_type_index
                                    : -1
                            }
                            onChange={(rawGroupTypeIndex) => {
                                const groupTypeIndex = rawGroupTypeIndex !== -1 ? rawGroupTypeIndex : undefined

                                setExperiment({
                                    parameters: {
                                        ...experiment.parameters,
                                        aggregation_group_type_index: groupTypeIndex ?? undefined,
                                    },
                                })
                            }}
                            options={[
                                { value: -1, label: 'Persons' },
                                ...Array.from(groupTypes.values()).map((groupType) => ({
                                    value: groupType.group_type_index,
                                    label: capitalizeFirstLetter(aggregationLabel(groupType.group_type_index).plural),
                                })),
                            ]}
                        />
                    </SceneSection>
                    <SceneDivider />
                </>
            )}
            {validExistingFeatureFlag && (
                <>
                    <SceneSection
                        title="Variants"
                        description="Existing feature flag configuration will be applied to the experiment."
                    >
                        <LemonBanner type="info">
                            <div className="flex items-center">
                                <div>Existing feature flag configuration will be applied to the experiment.</div>
                                <Link
                                    to={urls.featureFlag(validExistingFeatureFlag.id as number)}
                                    target="_blank"
                                    className="flex items-center"
                                >
                                    <IconOpenInNew className="ml-1" />
                                </Link>
                            </div>
                        </LemonBanner>
                    </SceneSection>
                    <SceneDivider />
                </>
            )}
            {!validExistingFeatureFlag && (
                <>
                    <SceneSection
                        title="Variants"
                        description={
                            <>Add up to {MAX_EXPERIMENT_VARIANTS - 1} variants to test against your control.</>
                        }
                    >
                        <div className="grid grid-cols-2 gap-4 max-w-160">
                            <div className="max-w-60">
                                <h3 className={cn('text-sm')}>Control</h3>
                                <div className="flex items-center">
                                    <Group key={0} name={['parameters', 'feature_flag_variants', 0]}>
                                        <ExperimentVariantNumber index={0} className="h-7 w-7 text-base" />
                                        <LemonField name="key" className="ml-2 flex-grow">
                                            <LemonInput
                                                disabled
                                                data-attr="experiment-variant-key"
                                                data-key-index={0}
                                                className="ph-ignore-input"
                                                fullWidth
                                                autoComplete="off"
                                                autoCapitalize="off"
                                                autoCorrect="off"
                                                spellCheck={false}
                                            />
                                        </LemonField>
                                    </Group>
                                </div>
                                <div className="text-secondary text-xs mt-2">
                                    Included automatically, cannot be edited or removed
                                </div>
                            </div>
                            <div className="max-w-100">
                                <h3 className={cn('text-sm')}>Test(s)</h3>
                                {experiment.parameters.feature_flag_variants?.map((_, index) => {
                                    if (index === 0) {
                                        return null
                                    }

                                    return (
                                        <Group key={index} name={['parameters', 'feature_flag_variants', index]}>
                                            <div
                                                key={`variant-${index}`}
                                                className={`flex items-center deprecated-space-x-2 ${
                                                    index > 1 && 'mt-2'
                                                }`}
                                            >
                                                <ExperimentVariantNumber index={index} className="h-7 w-7 text-base" />
                                                <LemonField name="key" className="flex-grow">
                                                    <LemonInput
                                                        data-attr="experiment-variant-key"
                                                        data-key-index={index.toString()}
                                                        className="ph-ignore-input"
                                                        fullWidth
                                                        autoComplete="off"
                                                        autoCapitalize="off"
                                                        autoCorrect="off"
                                                        spellCheck={false}
                                                    />
                                                </LemonField>
                                                <div className={`${index === 1 && 'pr-9'}`}>
                                                    {index !== 1 && (
                                                        <Tooltip title="Delete this variant" placement="top-start">
                                                            <LemonButton
                                                                size="small"
                                                                icon={<IconTrash />}
                                                                onClick={() => removeVariant(index)}
                                                            />
                                                        </Tooltip>
                                                    )}
                                                </div>
                                            </div>
                                        </Group>
                                    )
                                })}
                                <div className="text-secondary text-xs ml-9 mr-20 mt-2">
                                    Alphanumeric, hyphens and underscores only
                                </div>
                                {(experiment.parameters.feature_flag_variants.length ?? 0) <
                                    MAX_EXPERIMENT_VARIANTS && (
                                    <LemonButton
                                        className="ml-9 mt-2"
                                        type="secondary"
                                        onClick={() => addVariant()}
                                        icon={<IconPlusSmall />}
                                        data-attr="add-test-variant"
                                    >
                                        Add test variant
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </SceneSection>
                    <SceneDivider />
                    <div className={cn('mt-6 pb-2 max-w-150 mt-0 pb-0')}>
                        {featureFlags[FEATURE_FLAGS.EXPERIMENT_FORM_PERSISTENCE_FIELD] === 'test' ? (
                            <SceneSection
                                title={
                                    <span className="flex items-center gap-2">
                                        Variant persistence
                                        <Tooltip
                                            title={
                                                <span>
                                                    Only relevant if your experiment targets users transitioning from
                                                    anonymous to logged-in. Persistence requires PostHog servers to
                                                    perform the check and is incompatible with server-side local
                                                    evaluation. Learn more in the{' '}
                                                    <Link
                                                        to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                                                        target="_blank"
                                                        className="text-white underline"
                                                    >
                                                        documentation
                                                    </Link>
                                                    .
                                                </span>
                                            }
                                        >
                                            <IconInfo className="text-secondary text-lg" />
                                        </Tooltip>
                                    </span>
                                }
                                description="Choose how experiment variants are handled when users authenticate"
                            >
                                <LemonField name="parameters.ensure_experience_continuity">
                                    {({ value, onChange }) => {
                                        const currentValue = value ?? false
                                        return (
                                            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 max-w-160">
                                                {[
                                                    {
                                                        value: false,
                                                        icon: <IconX />,
                                                        title: 'Disabled (default)',
                                                        description: 'Users may see different variants after login.',
                                                    },
                                                    {
                                                        value: true,
                                                        icon: <IconLock />,
                                                        title: 'Persist across authentication',
                                                        description:
                                                            'Same variant before and after login. Incompatible with server-side flag evaluation.',
                                                    },
                                                ].map(({ value, icon, title, description }) => (
                                                    <div
                                                        key={value.toString()}
                                                        className={`border rounded-lg p-4 cursor-pointer transition-all hover:border-primary-light ${
                                                            currentValue === value
                                                                ? 'border-primary bg-primary-highlight'
                                                                : 'border-border'
                                                        }`}
                                                        onClick={() => onChange(value)}
                                                    >
                                                        <div className="flex items-start gap-3">
                                                            <div className="text-lg text-muted">{icon}</div>
                                                            <div className="flex-1">
                                                                <div className="font-medium text-sm">{title}</div>
                                                                <div className="text-xs text-muted mt-1">
                                                                    {description}
                                                                </div>
                                                            </div>
                                                            <input
                                                                type="radio"
                                                                name="persistence-mode"
                                                                checked={currentValue === value}
                                                                onChange={() => onChange(value)}
                                                                className="cursor-pointer"
                                                            />
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        )
                                    }}
                                </LemonField>
                            </SceneSection>
                        ) : (
                            <LemonField name="parameters.ensure_experience_continuity">
                                {({ value, onChange }) => (
                                    <label className="border rounded p-4 group" htmlFor="continuity-checkbox">
                                        <LemonCheckbox
                                            id="continuity-checkbox"
                                            label="Persist flag across authentication steps"
                                            onChange={() => onChange(!value)}
                                            fullWidth
                                            checked={value}
                                        />
                                        <div className="text-secondary text-sm pl-6">
                                            If your feature flag is evaluated for anonymous users, use this option to
                                            ensure the flag value remains consistent after the user logs in. Depending
                                            on your setup, this option may not always be appropriate. Note that this
                                            feature requires creating profiles for anonymous users.{' '}
                                            <Link
                                                to="https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps"
                                                target="_blank"
                                            >
                                                Learn more
                                            </Link>
                                        </div>
                                    </label>
                                )}
                            </LemonField>
                        )}
                    </div>
                </>
            )}
            <AccessControlAction
                resourceType={AccessControlResourceType.Experiment}
                minAccessLevel={AccessControlLevel.Editor}
                userAccessLevel={experiment.user_access_level}
            >
                <LemonButton
                    className={cn('w-fit')}
                    type="primary"
                    data-attr="save-experiment"
                    onClick={() => submitExperiment()}
                >
                    Save as draft
                </LemonButton>
            </AccessControlAction>
        </SceneContent>
    )
}

export const HoldoutSelector = (): JSX.Element => {
    const { experiment, holdouts } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)

    const holdoutOptions = holdouts.map((holdout) => ({
        value: holdout.id,
        label: holdout.name,
    }))
    holdoutOptions.unshift({ value: null, label: 'No holdout' })

    return (
        <div className="mt-4 mb-8">
            <LemonSelect
                options={holdoutOptions}
                value={experiment.holdout_id || null}
                onChange={(value) => {
                    setExperiment({
                        ...experiment,
                        holdout_id: value,
                    })
                }}
                data-attr="experiment-holdout-selector"
            />
        </div>
    )
}

export function ExperimentForm(): JSX.Element {
    const { props } = useValues(experimentLogic)

    return (
        <div>
            <Form
                id="experiment-step"
                logic={experimentLogic}
                formKey="experiment"
                props={props}
                enableFormOnSubmit
                className="deprecated-space-y-6 experiment-form"
            >
                <ExperimentFormFields />
            </Form>
        </div>
    )
}

const generateFeatureFlagKey = (name: string, unavailableFeatureFlagKeys: Set<string>): string => {
    const baseKey = name
        .toLowerCase()
        .replace(/[^A-Za-z0-9-_]+/g, '-')
        .replace(/-+$/, '')
        .replace(/^-+/, '')

    let key = baseKey
    let counter = 1

    while (unavailableFeatureFlagKeys.has(key)) {
        key = `${baseKey}-${counter}`
        counter++
    }
    return key
}

const SelectExistingFeatureFlagModal = ({
    isOpen,
    onClose,
    onSelect,
}: {
    isOpen: boolean
    onClose: () => void
    onSelect: (flag: FeatureFlagType) => void
}): JSX.Element => {
    const {
        featureFlagModalFeatureFlags,
        featureFlagModalFeatureFlagsLoading,
        featureFlagModalFilters,
        featureFlagModalPagination,
    } = useValues(experimentsLogic)
    const { setFeatureFlagModalFilters, resetFeatureFlagModalFilters } = useActions(experimentsLogic)

    const handleClose = (): void => {
        resetFeatureFlagModalFilters()
        onClose()
    }

    const filtersSection = (
        <div className="mb-4">
            <FeatureFlagFiltersSection
                filters={featureFlagModalFilters}
                setFeatureFlagsFilters={setFeatureFlagModalFilters}
                searchPlaceholder="Search for feature flags"
                filtersConfig={{ search: true }}
            />
        </div>
    )

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="Choose an existing feature flag" width="50%">
            <div className="deprecated-space-y-2">
                <div className="text-muted mb-2 max-w-xl">
                    Select an existing multivariate feature flag to use with this experiment. The feature flag must use
                    multiple variants with <code>'control'</code> as the first, and not be associated with an existing
                    experiment.
                </div>
                {filtersSection}
                <LemonTable
                    id="ff"
                    dataSource={featureFlagModalFeatureFlags.results.filter((featureFlag) => {
                        try {
                            return featureFlagEligibleForExperiment(featureFlag)
                        } catch {
                            return false
                        }
                    })}
                    loading={featureFlagModalFeatureFlagsLoading}
                    useURLForSorting={false}
                    columns={[
                        {
                            title: 'Key',
                            dataIndex: 'key',
                            sorter: (a, b) => (a.key || '').localeCompare(b.key || ''),
                            render: (key, flag) => (
                                <div className="flex items-center">
                                    <div className="font-semibold">{key}</div>
                                    <Link
                                        to={urls.featureFlag(flag.id as number)}
                                        target="_blank"
                                        className="flex items-center"
                                    >
                                        <IconOpenInNew className="ml-1" />
                                    </Link>
                                </div>
                            ),
                        },
                        {
                            title: 'Name',
                            dataIndex: 'name',
                            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
                        },
                        {
                            title: null,
                            render: function RenderActions(_, flag) {
                                return (
                                    <div className="flex items-center justify-end">
                                        <LemonButton
                                            size="xsmall"
                                            type="primary"
                                            disabledReason={undefined}
                                            onClick={() => {
                                                onSelect(flag)
                                                handleClose()
                                            }}
                                        >
                                            Select
                                        </LemonButton>
                                    </div>
                                )
                            },
                        },
                    ]}
                    emptyState="No feature flags match these filters."
                    pagination={featureFlagModalPagination}
                    onSort={(newSorting) =>
                        setFeatureFlagModalFilters({
                            order: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                            page: 1,
                        })
                    }
                />
            </div>
        </LemonModal>
    )
}
