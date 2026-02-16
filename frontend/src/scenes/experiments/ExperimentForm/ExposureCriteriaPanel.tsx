import { useValues } from 'kea'

import { LemonCollapse, LemonSelect, LemonTag } from '@posthog/lemon-ui'

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

const DEFAULT_EXPOSURE_CONFIG: ExperimentEventExposureConfig = {
    kind: NodeKind.ExperimentEventExposureConfig,
    event: '$feature_flag_called',
    properties: [],
}

type ExposureCriteriaPanelProps = {
    experiment: Experiment
    onChange: (exposureCriteria: ExperimentExposureCriteria) => void
    compact?: boolean
}

function InclusionActionFilter({
    experiment,
    onChange,
}: {
    experiment: Experiment
    onChange: ExposureCriteriaPanelProps['onChange']
}): JSX.Element {
    return (
        <ActionFilter
            bordered
            filters={exposureConfigToFilter(experiment.exposure_criteria?.exposure_config || DEFAULT_EXPOSURE_CONFIG)}
            setFilters={({ events, actions }: Partial<FilterType>): void => {
                const entity = events?.[0] || actions?.[0]
                if (entity) {
                    onChange({ exposure_config: filterToExposureConfig(entity) })
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
    )
}

function ExposureCriteriaFields({
    experiment,
    onChange,
    hasFilters,
}: {
    experiment: Experiment
    onChange: ExposureCriteriaPanelProps['onChange']
    hasFilters: boolean
}): JSX.Element {
    const isCustom = !!experiment.exposure_criteria?.exposure_config

    return (
        <div className="space-y-4">
            {/* Exposure Type Selection */}
            <label className="block text-sm font-medium text-default mb-2">Exposure criteria</label>
            <div className="flex gap-4 mb-4">
                <SelectableCard
                    title="Default"
                    description={
                        <>
                            When a <LemonTag>$feature_flag_called</LemonTag> event is recorded, a user is considered{' '}
                            <strong>exposed</strong> to the experiment.
                        </>
                    }
                    selected={!isCustom}
                    onClick={() => {
                        onChange({ exposure_config: undefined })
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
                    selected={isCustom}
                    onClick={() => {
                        onChange({
                            exposure_config: DEFAULT_EXPOSURE_CONFIG,
                        })
                    }}
                />
            </div>

            {isCustom && (
                <div className="mb-4">
                    <InclusionActionFilter experiment={experiment} onChange={onChange} />
                </div>
            )}

            {/* Multiple Variant Handling */}
            <div>
                <label className="block text-sm font-medium text-default mb-2">Multiple variant handling</label>
                <LemonSelect
                    value={experiment.exposure_criteria?.multiple_variant_handling || 'exclude'}
                    onChange={(value) => {
                        onChange({ multiple_variant_handling: value as 'exclude' | 'first_seen' })
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
                    {experiment.exposure_criteria?.multiple_variant_handling === 'first_seen'
                        ? 'Users exposed to multiple variants will be analyzed using their first seen variant.'
                        : 'Users exposed to multiple variants will be excluded from the analysis (recommended).'}
                </div>
            </div>

            {/* Test Account Filtering */}
            <div>
                <TestAccountFilterSwitch
                    checked={hasFilters && !!experiment.exposure_criteria?.filterTestAccounts}
                    onChange={(checked: boolean) => {
                        onChange({ filterTestAccounts: checked })
                    }}
                    bordered={false}
                    fullWidth
                    className="p-0"
                />
            </div>
        </div>
    )
}

export function ExposureCriteriaPanel({ experiment, onChange, compact }: ExposureCriteriaPanelProps): JSX.Element {
    const isCustom = !!experiment.exposure_criteria?.exposure_config

    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    if (compact) {
        return (
            <div className="space-y-4">
                <div className="space-y-3">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-sm text-secondary">Inclusion criteria</span>
                        <LemonSelect
                            size="small"
                            dropdownMatchSelectWidth={false}
                            dropdownPlacement="bottom-end"
                            value={isCustom ? 'custom' : 'default'}
                            onChange={(value) => {
                                if (value === 'custom') {
                                    onChange({
                                        exposure_config: DEFAULT_EXPOSURE_CONFIG,
                                    })
                                } else {
                                    onChange({ exposure_config: undefined })
                                }
                            }}
                            options={[
                                {
                                    value: 'default' as const,
                                    label: 'On feature flag',
                                    labelInMenu: (
                                        <div>
                                            <div>On feature flag</div>
                                            <div className="text-xs text-muted font-normal">
                                                When $feature_flag_called is recorded
                                            </div>
                                        </div>
                                    ),
                                },
                                {
                                    value: 'custom' as const,
                                    label: 'Custom event',
                                    labelInMenu: (
                                        <div>
                                            <div>Custom event</div>
                                            <div className="text-xs text-muted font-normal">
                                                Select a custom event to signal users reached the experiment
                                            </div>
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    </div>
                    {isCustom && <InclusionActionFilter experiment={experiment} onChange={onChange} />}
                </div>

                <div className="flex items-center justify-between gap-2">
                    <span className="text-sm text-secondary">Multiple variant handling</span>
                    <LemonSelect
                        size="small"
                        dropdownMatchSelectWidth={false}
                        dropdownPlacement="bottom-end"
                        value={experiment.exposure_criteria?.multiple_variant_handling || 'exclude'}
                        onChange={(value) => {
                            onChange({ multiple_variant_handling: value as 'exclude' | 'first_seen' })
                        }}
                        options={[
                            {
                                value: 'exclude',
                                label: 'Exclude multi-variant users',
                                labelInMenu: (
                                    <div>
                                        <div>Exclude multi-variant users</div>
                                        <div className="text-xs text-muted font-normal">
                                            Users exposed to multiple variants will be excluded (recommended)
                                        </div>
                                    </div>
                                ),
                                'data-attr': 'multiple-handling-exclude',
                            },
                            {
                                value: 'first_seen',
                                label: 'Use first seen variant',
                                labelInMenu: (
                                    <div>
                                        <div>Use first seen variant</div>
                                        <div className="text-xs text-muted font-normal">
                                            Users will be analyzed using their first seen variant
                                        </div>
                                    </div>
                                ),
                                'data-attr': 'multiple-handling-first-seen',
                            },
                        ]}
                    />
                </div>

                <TestAccountFilterSwitch
                    checked={hasFilters && !!experiment.exposure_criteria?.filterTestAccounts}
                    onChange={(checked: boolean) => {
                        onChange({ filterTestAccounts: checked })
                    }}
                    bordered={false}
                    fullWidth
                    labelClassName="text-secondary"
                    className="p-0"
                />
            </div>
        )
    }

    return (
        <div className="space-y-4">
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
                                        Configure when users are considered exposed to the experiment and included in
                                        the analysis.
                                    </div>
                                </div>
                            ),
                        },
                        content: (
                            <div className="p-3">
                                <ExposureCriteriaFields
                                    experiment={experiment}
                                    onChange={onChange}
                                    hasFilters={hasFilters}
                                />
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
