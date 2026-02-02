import { useValues } from 'kea'

import { LemonButton, LemonCollapse, LemonDivider, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { ExperimentEventExposureConfig, ExperimentExposureCriteria, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment, FilterType } from '~/types'

import { commonActionFilterProps } from '../Metrics/Selectors'
import { SelectableCard } from '../components/SelectableCard'
import { exposureConfigToFilter, filterToExposureConfig } from '../utils'

type ExposureCriteriaPanelProps = {
    experiment: Experiment
    onChange: (exposureCriteria: ExperimentExposureCriteria) => void
    onNext: () => void
    showNewExperimentFormLayout?: boolean
}

export function ExposureCriteriaPanel({
    experiment,
    onChange,
    onNext,
    showNewExperimentFormLayout = false,
}: ExposureCriteriaPanelProps): JSX.Element {
    // Derive exposure type from experiment state
    const selectedExposureType = experiment.exposure_criteria?.exposure_config ? 'custom' : 'default'

    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    if (showNewExperimentFormLayout) {
        return (
            <div className="space-y-4">
                {/* Advanced Settings */}
                <LemonCollapse
                    panels={[
                        {
                            key: 'advanced-settings',
                            header: {
                                style: { backgroundColor: 'var(--color-bg-table)' },
                                children: (
                                    <div>
                                        <h3 className="l4 mt-2 font-semibold">Advanced settings</h3>
                                        <div className="text-secondary mb-2 text-sm font-normal">
                                            Configure when users are considered exposed to the experiment and included
                                            in the analysis.
                                        </div>
                                    </div>
                                ),
                            },
                            content: (
                                <div className="p-3 space-y-4">
                                    {/* Exposure Type Selection */}
                                    <label className="block text-sm font-medium text-default mb-2">
                                        Exposure criteria
                                    </label>
                                    <div className="flex gap-4 mb-4">
                                        <SelectableCard
                                            title="Default"
                                            description={
                                                <>
                                                    When a <LemonTag>$feature_flag_called</LemonTag> event is recorded,
                                                    a user is considered <strong>exposed</strong> to the experiment.
                                                </>
                                            }
                                            selected={selectedExposureType === 'default'}
                                            onClick={() => {
                                                onChange({
                                                    exposure_config: undefined,
                                                })
                                            }}
                                        />
                                        <SelectableCard
                                            title="Custom"
                                            description={
                                                <>
                                                    Select a custom event to signal that users reached the part of your
                                                    app where the experiment runs. You can also filter out users you
                                                    would like to exclude.
                                                </>
                                            }
                                            selected={selectedExposureType === 'custom'}
                                            onClick={() => {
                                                onChange({
                                                    exposure_config: {
                                                        kind: NodeKind.ExperimentEventExposureConfig,
                                                        event: '$feature_flag_called',
                                                        properties: [],
                                                    },
                                                })
                                            }}
                                        />
                                    </div>

                                    {/* Custom Event Configuration */}
                                    {selectedExposureType === 'custom' && (
                                        <div className="mb-4">
                                            <ActionFilter
                                                bordered
                                                filters={exposureConfigToFilter(
                                                    experiment.exposure_criteria?.exposure_config ||
                                                        ({
                                                            kind: NodeKind.ExperimentEventExposureConfig,
                                                            event: '$feature_flag_called',
                                                            properties: [],
                                                        } as ExperimentEventExposureConfig)
                                                )}
                                                setFilters={({ events, actions }: Partial<FilterType>): void => {
                                                    const entity = events?.[0] || actions?.[0]
                                                    if (entity) {
                                                        onChange({
                                                            exposure_config: filterToExposureConfig(entity),
                                                        })
                                                    }
                                                }}
                                                typeKey="experiment-exposure-config"
                                                buttonCopy="Add exposure event"
                                                showSeriesIndicator={false}
                                                hideRename={true}
                                                entitiesLimit={1}
                                                mathAvailability={MathAvailability.None}
                                                showNumericalPropsOnly={false}
                                                actionsTaxonomicGroupTypes={[
                                                    TaxonomicFilterGroupType.Events,
                                                    TaxonomicFilterGroupType.Actions,
                                                ]}
                                                propertiesTaxonomicGroupTypes={
                                                    commonActionFilterProps.propertiesTaxonomicGroupTypes
                                                }
                                            />
                                        </div>
                                    )}

                                    {/* Multiple Variant Handling */}
                                    <div>
                                        <label className="block text-sm font-medium text-default mb-2">
                                            Multiple variant handling
                                        </label>
                                        <LemonSelect
                                            value={experiment.exposure_criteria?.multiple_variant_handling || 'exclude'}
                                            onChange={(value) => {
                                                onChange({
                                                    multiple_variant_handling: value as 'exclude' | 'first_seen',
                                                })
                                            }}
                                            options={[
                                                {
                                                    value: 'exclude',
                                                    label: 'Exclude from analysis',
                                                    'data-attr': 'multiple-handling-exclude',
                                                },
                                                {
                                                    value: 'first_seen',
                                                    label: 'Use first seen variant',
                                                    'data-attr': 'multiple-handling-first-seen',
                                                },
                                            ]}
                                            placeholder="Select handling method"
                                            fullWidth
                                        />
                                        <div className="text-xs text-muted mt-1">
                                            {experiment.exposure_criteria?.multiple_variant_handling === 'first_seen' &&
                                                'Users exposed to multiple variants will be analyzed using their first seen variant.'}
                                            {(!experiment.exposure_criteria?.multiple_variant_handling ||
                                                experiment.exposure_criteria?.multiple_variant_handling ===
                                                    'exclude') &&
                                                'Users exposed to multiple variants will be excluded from the analysis (recommended).'}
                                        </div>
                                    </div>
                                    {/* Test Account Filtering */}
                                    <div>
                                        <TestAccountFilterSwitch
                                            checked={(() => {
                                                const val = experiment.exposure_criteria?.filterTestAccounts
                                                return hasFilters ? !!val : false
                                            })()}
                                            onChange={(checked: boolean) => {
                                                onChange({
                                                    filterTestAccounts: checked,
                                                })
                                            }}
                                            bordered={false}
                                            fullWidth
                                            className="p-0"
                                        />
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div className="text-sm text-muted">
                Configure when users are considered exposed to the experiment and included in the analysis.
            </div>

            {/* Exposure Type Selection */}
            <div className="flex gap-4 mb-4">
                <SelectableCard
                    title="Default"
                    description={
                        <>
                            When a <LemonTag>$feature_flag_called</LemonTag> event is recorded, a user is considered{' '}
                            <strong>exposed</strong> to the experiment.
                        </>
                    }
                    selected={selectedExposureType === 'default'}
                    onClick={() => {
                        onChange({
                            exposure_config: undefined,
                        })
                    }}
                />
                <SelectableCard
                    title="Custom"
                    description={
                        <>
                            Select a custom event to signal that users reached the part of your app where the experiment
                            runs. You can also filter out users you would like to exclude.
                        </>
                    }
                    selected={selectedExposureType === 'custom'}
                    onClick={() => {
                        onChange({
                            exposure_config: {
                                kind: NodeKind.ExperimentEventExposureConfig,
                                event: '$feature_flag_called',
                                properties: [],
                            },
                        })
                    }}
                />
            </div>

            {/* Custom Event Configuration */}
            {selectedExposureType === 'custom' && (
                <div className="mb-4">
                    <ActionFilter
                        bordered
                        filters={exposureConfigToFilter(
                            experiment.exposure_criteria?.exposure_config ||
                                ({
                                    kind: NodeKind.ExperimentEventExposureConfig,
                                    event: '$feature_flag_called',
                                    properties: [],
                                } as ExperimentEventExposureConfig)
                        )}
                        setFilters={({ events, actions }: Partial<FilterType>): void => {
                            const entity = events?.[0] || actions?.[0]
                            if (entity) {
                                onChange({
                                    exposure_config: filterToExposureConfig(entity),
                                })
                            }
                        }}
                        typeKey="experiment-exposure-config"
                        buttonCopy="Add exposure event"
                        showSeriesIndicator={false}
                        hideRename={true}
                        entitiesLimit={1}
                        mathAvailability={MathAvailability.None}
                        showNumericalPropsOnly={false}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                        propertiesTaxonomicGroupTypes={commonActionFilterProps.propertiesTaxonomicGroupTypes}
                    />
                </div>
            )}

            {/* Advanced Settings */}
            <LemonCollapse
                panels={[
                    {
                        key: 'advanced-settings',
                        header: {
                            style: { backgroundColor: 'var(--color-bg-table)' },
                            children: (
                                <div>
                                    <h3 className="l4 mt-2 font-semibold">Advanced settings</h3>
                                    <div className="text-secondary mb-2 text-sm font-normal">
                                        Configure additional exposure options.
                                    </div>
                                </div>
                            ),
                        },
                        content: (
                            <div className="p-3 space-y-4">
                                {/* Multiple Variant Handling */}
                                <div>
                                    <label className="block text-sm font-medium text-default mb-2">
                                        Multiple variant handling
                                    </label>
                                    <LemonSelect
                                        value={experiment.exposure_criteria?.multiple_variant_handling || 'exclude'}
                                        onChange={(value) => {
                                            onChange({
                                                multiple_variant_handling: value as 'exclude' | 'first_seen',
                                            })
                                        }}
                                        options={[
                                            {
                                                value: 'exclude',
                                                label: 'Exclude from analysis',
                                                'data-attr': 'multiple-handling-exclude',
                                            },
                                            {
                                                value: 'first_seen',
                                                label: 'Use first seen variant',
                                                'data-attr': 'multiple-handling-first-seen',
                                            },
                                        ]}
                                        placeholder="Select handling method"
                                        fullWidth
                                    />
                                    <div className="text-xs text-muted mt-1">
                                        {experiment.exposure_criteria?.multiple_variant_handling === 'first_seen' &&
                                            'Users exposed to multiple variants will be analyzed using their first seen variant.'}
                                        {(!experiment.exposure_criteria?.multiple_variant_handling ||
                                            experiment.exposure_criteria?.multiple_variant_handling === 'exclude') &&
                                            'Users exposed to multiple variants will be excluded from the analysis (recommended).'}
                                    </div>
                                </div>
                                {/* Test Account Filtering */}
                                <div>
                                    <TestAccountFilterSwitch
                                        checked={(() => {
                                            const val = experiment.exposure_criteria?.filterTestAccounts
                                            return hasFilters ? !!val : false
                                        })()}
                                        onChange={(checked: boolean) => {
                                            onChange({
                                                filterTestAccounts: checked,
                                            })
                                        }}
                                        bordered={false}
                                        fullWidth
                                        className="p-0"
                                    />
                                </div>
                            </div>
                        ),
                    },
                ]}
            />

            <LemonDivider />
            <div className="flex justify-end pt-2">
                <LemonButton type="primary" size="small" onClick={onNext}>
                    Next
                </LemonButton>
            </div>
        </div>
    )
}
