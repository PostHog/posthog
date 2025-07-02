import { IconPlusSmall, IconToggle, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonCheckbox,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonTable,
    LemonTextArea,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { ExperimentVariantNumber } from 'lib/components/SeriesGlyph'
import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useState } from 'react'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { urls } from 'scenes/urls'

import { FeatureFlagType } from '~/types'

import { experimentLogic } from './experimentLogic'
import { featureFlagEligibleForExperiment } from './utils'

const ExperimentFormFields = (): JSX.Element => {
    const { formMode, experiment, groupTypes, aggregationLabel, hasPrimaryMetricSet, validExistingFeatureFlag } =
        useValues(experimentLogic)
    const { addVariant, removeVariant, setExperiment, submitExperiment, setExperimentType, validateFeatureFlag } =
        useActions(experimentLogic)
    const { webExperimentsAvailable, unavailableFeatureFlagKeys } = useValues(experimentsLogic)
    const { groupsAccessStatus } = useValues(groupsAccessLogic)

    const { reportExperimentFeatureFlagModalOpened, reportExperimentFeatureFlagSelected } = useActions(eventUsageLogic)

    const [showFeatureFlagSelector, setShowFeatureFlagSelector] = useState(false)

    return (
        <div>
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
            <div className="deprecated-space-y-8">
                <div className="deprecated-space-y-6 max-w-120">
                    <LemonField name="name" label="Name">
                        <LemonInput
                            placeholder="Pricing page conversion"
                            data-attr="experiment-name"
                            onBlur={() => {
                                // bail if feature flag key is already set
                                if (experiment.feature_flag_key) {
                                    return
                                }

                                setExperiment({
                                    feature_flag_key: generateFeatureFlagKey(
                                        experiment.name,
                                        unavailableFeatureFlagKeys
                                    ),
                                })
                            }}
                        />
                    </LemonField>
                    <LemonField
                        name="feature_flag_key"
                        label="Feature flag key"
                        help={
                            <div className="flex items-center justify-between">
                                <span>Each experiment is backed by a feature flag.</span>
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
                        <LemonInput placeholder="pricing-page-conversion" data-attr="experiment-feature-flag-key" />
                    </LemonField>
                    <LemonField name="description" label="Description">
                        <LemonTextArea
                            placeholder="The goal of this experiment is ..."
                            data-attr="experiment-description"
                        />
                    </LemonField>
                </div>
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
                    <div className="mt-10">
                        <h3 className="mb-1">Experiment type</h3>
                        <div className="text-xs text-secondary font-medium tracking-normal">
                            Select your experiment setup, this cannot be changed once saved.
                        </div>
                        <LemonDivider />
                        <LemonRadio
                            value={experiment.type}
                            className="deprecated-space-y-2 -mt-2"
                            onChange={(type) => {
                                setExperimentType(type)
                            }}
                            options={[
                                {
                                    value: 'product',
                                    label: (
                                        <div className="translate-y-2">
                                            <div>Product experiment</div>
                                            <div className="text-xs text-secondary">
                                                Use custom code to manage how variants modify your product.
                                            </div>
                                        </div>
                                    ),
                                },
                                {
                                    value: 'web',
                                    label: (
                                        <div className="translate-y-2">
                                            <div>No-code web experiment</div>
                                            <div className="text-xs text-secondary">
                                                Define variants on your website using the PostHog toolbar, no coding
                                                required.
                                            </div>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    </div>
                )}
                {groupsAccessStatus === GroupsAccessStatus.AlreadyUsing && (
                    <div className="mt-10">
                        <h3>Participant type</h3>
                        <div className="text-xs text-secondary  max-w-150">
                            Determines on what level you want to aggregate metrics. You can change this later, but flag
                            values for users will change so you need to reset the experiment for accurate results.
                        </div>
                        <LemonDivider />
                        <LemonRadio
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
                    </div>
                )}
                {validExistingFeatureFlag && (
                    <div className="mt-10">
                        <h3 className="mb-1">Variants</h3>
                        <LemonDivider />
                        <LemonBanner type="info" className="mb-8">
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
                    </div>
                )}
                {!validExistingFeatureFlag && (
                    <>
                        <div className="mt-10">
                            <h3 className="mb-1">Variants</h3>
                            <div className="text-xs text-secondary">
                                Add up to {MAX_EXPERIMENT_VARIANTS - 1} variants to test against your control.
                            </div>
                            <LemonDivider />
                            <div className="grid grid-cols-2 gap-4 max-w-160">
                                <div className="max-w-60">
                                    <h3>Control</h3>
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
                                    <div className="text-muted text-xs mt-2">
                                        Included automatically, cannot be edited or removed
                                    </div>
                                </div>
                                <div className="max-w-100">
                                    <h3>Test(s)</h3>
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
                                                    <ExperimentVariantNumber
                                                        index={index}
                                                        className="h-7 w-7 text-base"
                                                    />
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
                        </div>
                        <div className="mt-10 max-w-150">
                            <LemonField name="parameters.ensure_experience_continuity">
                                {({ value, onChange }) => (
                                    <div className="border rounded p-4">
                                        <LemonCheckbox
                                            id="continuity-checkbox"
                                            label="Persist flag across authentication steps"
                                            onChange={() => onChange(!value)}
                                            fullWidth
                                            checked={value}
                                        />
                                        <div className="text-secondary text-sm pl-7">
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
                                    </div>
                                )}
                            </LemonField>
                        </div>
                    </>
                )}
            </div>
            <LemonButton className="mt-2" type="primary" data-attr="save-experiment" onClick={() => submitExperiment()}>
                Save as draft
            </LemonButton>
        </div>
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
    const { featureFlags } = useValues(experimentsLogic)

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} title="Choose an existing feature flag">
            <div className="deprecated-space-y-2">
                <div className="text-muted mb-2 max-w-xl">
                    Select an existing feature flag to use with this experiment. The feature flag must use multiple
                    variants with <code>'control'</code> as the first, and not be associated with an existing
                    experiment.
                </div>
                <LemonTable
                    dataSource={featureFlags.results}
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
                                let disabledReason: string | undefined = undefined
                                try {
                                    featureFlagEligibleForExperiment(flag)
                                } catch (error) {
                                    disabledReason = (error as Error).message
                                }
                                return (
                                    <LemonButton
                                        size="xsmall"
                                        type="primary"
                                        disabledReason={disabledReason}
                                        onClick={() => {
                                            onSelect(flag)
                                            onClose()
                                        }}
                                    >
                                        Select
                                    </LemonButton>
                                )
                            },
                        },
                    ]}
                />
            </div>
        </LemonModal>
    )
}
