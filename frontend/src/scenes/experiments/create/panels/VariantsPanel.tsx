import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconBalance, IconPlus, IconToggle, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { MAX_EXPERIMENT_VARIANTS } from 'lib/constants'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { alphabet } from 'lib/utils'
import { JSONEditorInput } from 'scenes/feature-flags/JSONEditorInput'
import { urls } from 'scenes/urls'

import type { Experiment, FeatureFlagType, MultivariateFlagVariant } from '~/types'

import { SelectableCard } from '../../components/SelectableCard'
import { percentageDistribution } from '../../utils'
import { variantsPanelLogic } from './variantsPanelLogic'

interface VariantsPanelProps {
    experiment: Experiment
    onChange: (updates: {
        feature_flag_key?: string
        parameters?: {
            feature_flag_variants?: MultivariateFlagVariant[]
            ensure_experience_continuity?: boolean
        }
    }) => void
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
    const [search, setSearch] = useState('')
    const { availableFeatureFlags, availableFeatureFlagsLoading } = useValues(variantsPanelLogic)
    const { searchFeatureFlags, resetFeatureFlagsSearch, loadAllEligibleFeatureFlags } = useActions(variantsPanelLogic)

    useEffect(() => {
        // Load all eligible feature flags when modal opens
        loadAllEligibleFeatureFlags()
    }, [loadAllEligibleFeatureFlags])

    useEffect(() => {
        if (search) {
            searchFeatureFlags(search)
        } else {
            // If search is cleared, reload all flags
            loadAllEligibleFeatureFlags()
        }
    }, [search, loadAllEligibleFeatureFlags, searchFeatureFlags])

    const handleClose = (): void => {
        resetFeatureFlagsSearch()
        setSearch('')
        onClose()
    }

    return (
        <LemonModal isOpen={isOpen} onClose={handleClose} title="Choose an existing feature flag" width="50%">
            <div className="space-y-2">
                <div className="text-muted mb-2 max-w-xl">
                    Select an existing multivariate feature flag to use with this experiment. The feature flag must use
                    multiple variants with <code>'control'</code> as the first, and not be associated with an existing
                    experiment.
                </div>
                <div className="mb-4">
                    <LemonInput
                        type="search"
                        placeholder="Search for feature flags"
                        value={search}
                        onChange={setSearch}
                        fullWidth
                    />
                </div>
                <LemonTable
                    id="ff"
                    dataSource={availableFeatureFlags}
                    loading={availableFeatureFlagsLoading}
                    columns={[
                        {
                            title: 'Key',
                            dataIndex: 'key',
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
                        },
                        {
                            title: null,
                            render: function RenderActions(_, flag) {
                                return (
                                    <div className="flex items-center justify-end">
                                        <LemonButton
                                            size="xsmall"
                                            type="primary"
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
                    emptyState="No feature flags match your search. Try different keywords."
                />
            </div>
        </LemonModal>
    )
}

export function VariantsPanel({ experiment, onChange }: VariantsPanelProps): JSX.Element {
    const [flagSourceMode, setFlagSourceMode] = useState<'create' | 'link'>('create')

    const [linkedFeatureFlag, setLinkedFeatureFlag] = useState<FeatureFlagType | null>(null)
    const [showFeatureFlagSelector, setShowFeatureFlagSelector] = useState(false)
    const [localFeatureFlagKey, setLocalFeatureFlagKey] = useState(experiment.feature_flag_key || '')
    // Store the created key separately to preserve it when switching modes
    const [savedCreatedKey, setSavedCreatedKey] = useState(experiment.feature_flag_key || '')

    const { validateFeatureFlagKey, generateFeatureFlagKey } = useActions(variantsPanelLogic)
    const { featureFlagKeyValidation, generatedKey } = useValues(variantsPanelLogic)

    const variants = experiment.parameters?.feature_flag_variants || [
        { key: 'control', rollout_percentage: 50 },
        { key: 'test', rollout_percentage: 50 },
    ]
    const ensureExperienceContinuity = (experiment.parameters as any)?.ensure_experience_continuity ?? true

    const variantRolloutSum = variants.reduce((sum, v) => sum + v.rollout_percentage, 0)
    const areVariantRolloutsValid =
        variants.every(({ rollout_percentage }) => rollout_percentage >= 0 && rollout_percentage <= 100) &&
        variantRolloutSum === 100

    const updateVariant = (index: number, updates: Partial<MultivariateFlagVariant>): void => {
        const newVariants = [...variants]
        newVariants[index] = { ...newVariants[index], ...updates }
        onChange({ parameters: { ...experiment.parameters, feature_flag_variants: newVariants } })
    }

    const addVariant = (): void => {
        if (variants.length >= MAX_EXPERIMENT_VARIANTS) {
            return
        }
        const newVariant: MultivariateFlagVariant = {
            key: `test-${variants.length}`,
            rollout_percentage: 0,
        }
        const newVariants = [...variants, newVariant]
        distributeVariantsEqually(newVariants)
    }

    const removeVariant = (index: number): void => {
        if (variants.length <= 2 || index === 0) {
            return
        }
        const newVariants = variants.filter((_, i) => i !== index)
        distributeVariantsEqually(newVariants)
    }

    const distributeVariantsEqually = (variantsToDistribute?: MultivariateFlagVariant[]): void => {
        const variantsToUse = variantsToDistribute || variants
        const percentages = percentageDistribution(variantsToUse.length)
        const newVariants = variantsToUse.map((variant, index) => ({
            ...variant,
            rollout_percentage: percentages[index],
        }))
        onChange({ parameters: { ...experiment.parameters, feature_flag_variants: newVariants } })
    }

    // Handle generated key updates
    useEffect(() => {
        if (generatedKey && flagSourceMode === 'create') {
            setLocalFeatureFlagKey(generatedKey)
            setSavedCreatedKey(generatedKey)
            onChange({ feature_flag_key: generatedKey })
            validateFeatureFlagKey(generatedKey)
        }
    }, [generatedKey, flagSourceMode, onChange, validateFeatureFlagKey])

    useEffect(() => {
        if (flagSourceMode === 'create' && localFeatureFlagKey && localFeatureFlagKey !== experiment.feature_flag_key) {
            onChange({ feature_flag_key: localFeatureFlagKey })
            setSavedCreatedKey(localFeatureFlagKey)
            validateFeatureFlagKey(localFeatureFlagKey)
        }
    }, [localFeatureFlagKey, flagSourceMode, experiment.feature_flag_key, validateFeatureFlagKey, onChange])

    useEffect(() => {
        if (linkedFeatureFlag) {
            onChange({
                feature_flag_key: linkedFeatureFlag.key,
                parameters: {
                    ...experiment.parameters,
                    feature_flag_variants: linkedFeatureFlag.filters?.multivariate?.variants || [],
                },
            })
        }
    }, [linkedFeatureFlag, experiment.parameters, onChange])

    return (
        <div className="space-y-6">
            {/* Feature Flag Source Selection */}
            <div>
                <h3 className="font-semibold mb-3">Feature Flag Configuration</h3>
                <div className="flex gap-4 mb-6">
                    <SelectableCard
                        title="Create new feature flag"
                        description="Generate a new feature flag with custom variants for this experiment."
                        selected={flagSourceMode === 'create'}
                        onClick={() => {
                            setFlagSourceMode('create')
                            setLinkedFeatureFlag(null)
                            // Restore the previously created key when switching back
                            if (savedCreatedKey) {
                                setLocalFeatureFlagKey(savedCreatedKey)
                                onChange({ feature_flag_key: savedCreatedKey })
                            }
                        }}
                    />
                    <SelectableCard
                        title="Link existing feature flag"
                        description="Use an existing multivariate feature flag and inherit its variants."
                        selected={flagSourceMode === 'link'}
                        onClick={() => setFlagSourceMode('link')}
                    />
                </div>
            </div>

            {/* Feature Flag Key - Show for create mode */}
            {flagSourceMode === 'create' && (
                <div className="max-w-2xl">
                    <label className="text-sm font-semibold">Feature flag key</label>
                    <LemonInput
                        className="mt-1"
                        placeholder="pricing-page-conversion"
                        data-attr="experiment-feature-flag-key"
                        value={localFeatureFlagKey}
                        onChange={(value) => {
                            setLocalFeatureFlagKey(value)
                            validateFeatureFlagKey(value)
                        }}
                        onFocus={() => {
                            if (!localFeatureFlagKey && experiment.name) {
                                generateFeatureFlagKey(experiment.name)
                            }
                        }}
                        status={featureFlagKeyValidation && !featureFlagKeyValidation.valid ? 'danger' : undefined}
                    />
                    {featureFlagKeyValidation?.error && (
                        <div className="text-xs text-danger mt-1">{featureFlagKeyValidation.error}</div>
                    )}
                    <div className="text-xs text-muted mt-1">
                        Each experiment is backed by a feature flag. This key will be used to control the experiment in
                        your code.
                    </div>
                </div>
            )}

            {/* Linked Feature Flag Section */}
            {flagSourceMode === 'link' && (
                <div className="max-w-2xl">
                    <label className="text-sm font-semibold">Selected Feature Flag</label>
                    {!linkedFeatureFlag ? (
                        <div className="mt-2 p-4 border border-dashed rounded bg-surface-light">
                            <div className="text-center">
                                <div className="text-sm text-muted mb-2">No feature flag selected</div>
                                <LemonButton type="primary" onClick={() => setShowFeatureFlagSelector(true)}>
                                    Select Feature Flag
                                </LemonButton>
                            </div>
                        </div>
                    ) : (
                        <div className="mt-2 border-2 border-primary-light rounded-lg bg-primary-highlight p-4">
                            <div className="flex justify-between items-start gap-4">
                                <div className="flex-1">
                                    <div className="flex items-center gap-2">
                                        <IconToggle className="text-primary" />
                                        <div className="font-semibold text-base">{linkedFeatureFlag.key}</div>
                                        <Link
                                            to={urls.featureFlag(linkedFeatureFlag.id as number)}
                                            target="_blank"
                                            className="flex items-center text-primary hover:text-primary-dark"
                                        >
                                            <IconOpenInNew className="text-lg" />
                                        </Link>
                                    </div>
                                    {linkedFeatureFlag.name && (
                                        <div className="text-muted-alt mt-1">{linkedFeatureFlag.name}</div>
                                    )}
                                    <div className="mt-3 flex items-center gap-4">
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs font-medium text-muted">VARIANTS:</span>
                                            <div className="flex gap-1">
                                                {linkedFeatureFlag.filters?.multivariate?.variants?.map((v, idx) => (
                                                    <span
                                                        key={idx}
                                                        className="inline-flex items-center px-2 py-0.5 rounded-md bg-bg-light text-xs font-medium"
                                                    >
                                                        {v.key}
                                                    </span>
                                                )) || []}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    onClick={() => setShowFeatureFlagSelector(true)}
                                >
                                    Change
                                </LemonButton>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Variant keys - Only show for create mode */}
            {flagSourceMode === 'create' && (
                <div>
                    <h3 className="font-semibold mb-2">Variant keys</h3>
                    <div className="text-sm text-muted mb-4">
                        The rollout percentage of feature flag variants must add up to 100%
                    </div>

                    <div className="p-4 mt-4 text-sm border border-primary rounded">
                        <div className="grid grid-cols-24 gap-2 font-bold mb-2">
                            <div />
                            <div className="col-span-4">Variant key</div>
                            <div className="col-span-6">Description</div>
                            <div className="col-span-8">
                                <div className="flex flex-col">
                                    <span>Payload</span>
                                    <span className="text-secondary font-normal">
                                        Specify return payload when the variant key matches
                                    </span>
                                </div>
                            </div>
                            <div className="col-span-3 flex justify-between items-center gap-1">
                                <span>Rollout</span>
                                <LemonButton
                                    onClick={() => distributeVariantsEqually()}
                                    tooltip="Normalize variant rollout percentages"
                                >
                                    <IconBalance />
                                </LemonButton>
                            </div>
                        </div>
                        {variants.map((variant, index) => (
                            <div key={index} className="grid grid-cols-24 gap-2 mb-2">
                                <div className="flex items-center justify-center">
                                    <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                </div>
                                <div className="col-span-4">
                                    <LemonInput
                                        value={variant.key}
                                        onChange={(value) => updateVariant(index, { key: value })}
                                        data-attr="experiment-variant-key"
                                        data-key-index={index.toString()}
                                        className="ph-ignore-input"
                                        placeholder={`example-variant-${index + 1}`}
                                        autoComplete="off"
                                        autoCapitalize="off"
                                        autoCorrect="off"
                                        spellCheck={false}
                                    />
                                </div>
                                <div className="col-span-6">
                                    <LemonInput
                                        value={variant.name || ''}
                                        onChange={(value) => updateVariant(index, { name: value })}
                                        data-attr="experiment-variant-name"
                                        className="ph-ignore-input"
                                        placeholder="Description"
                                    />
                                </div>
                                <div className="col-span-8">
                                    <JSONEditorInput
                                        onChange={(newValue) => {
                                            const updatedVariant = { ...variant }
                                            if (newValue === '') {
                                                delete (updatedVariant as any).payload
                                            } else {
                                                ;(updatedVariant as any).payload = newValue
                                            }
                                            updateVariant(index, updatedVariant)
                                        }}
                                        value={(variant as any).payload || ''}
                                        placeholder='{"key": "value"}'
                                    />
                                </div>
                                <div className="col-span-3">
                                    <LemonInput
                                        type="number"
                                        min={0}
                                        max={100}
                                        value={variant.rollout_percentage}
                                        onChange={(changedValue) => {
                                            const valueInt =
                                                changedValue !== undefined && !isNaN(changedValue)
                                                    ? parseInt(changedValue.toString())
                                                    : 0
                                            updateVariant(index, { rollout_percentage: valueInt })
                                        }}
                                        suffix={<span>%</span>}
                                        data-attr="experiment-variant-rollout-percentage-input"
                                    />
                                </div>
                                <div className="flex items-center justify-center">
                                    {variants.length > 2 && index > 0 && (
                                        <LemonButton
                                            icon={<IconTrash />}
                                            data-attr={`delete-prop-filter-${index}`}
                                            noPadding
                                            onClick={() => removeVariant(index)}
                                            tooltipPlacement="top-end"
                                        />
                                    )}
                                </div>
                            </div>
                        ))}
                        {variants.length > 0 && !areVariantRolloutsValid && (
                            <p className="text-danger">
                                Percentage rollouts for variants must sum to 100 (currently {variantRolloutSum}).
                            </p>
                        )}
                        {variants.length < MAX_EXPERIMENT_VARIANTS && (
                            <LemonButton type="secondary" onClick={addVariant} icon={<IconPlus />} center>
                                Add variant
                            </LemonButton>
                        )}
                    </div>
                </div>
            )}

            {/* Variant Persistence */}
            <div className="max-w-2xl">
                <LemonCheckbox
                    id="continuity-checkbox"
                    label="Persist flag across authentication steps"
                    onChange={(checked) => {
                        onChange({
                            parameters: {
                                ...experiment.parameters,
                                ensure_experience_continuity: checked,
                            } as any,
                        })
                    }}
                    fullWidth
                    checked={ensureExperienceContinuity}
                />
                <div className="text-secondary text-sm pl-6 mt-2">
                    If your feature flag is evaluated for anonymous users, use this option to ensure the flag value
                    remains consistent after the user logs in. Note that this feature requires creating profiles for
                    anonymous users.
                </div>
            </div>

            {/* Feature Flag Selection Modal */}
            <SelectExistingFeatureFlagModal
                isOpen={showFeatureFlagSelector}
                onClose={() => setShowFeatureFlagSelector(false)}
                onSelect={(flag) => {
                    setLinkedFeatureFlag(flag)
                    setShowFeatureFlagSelector(false)
                }}
            />
        </div>
    )
}
