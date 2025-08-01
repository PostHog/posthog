import { LemonButton, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { commonActionFilterProps } from '../Metrics/Selectors'
import { exposureConfigToFilter, filterToExposureConfig } from '../utils'
import { modalsLogic } from '../modalsLogic'
import { SelectableCard } from '../components/SelectableCard'

export function ExposureCriteriaModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { restoreUnmodifiedExperiment, setExposureCriteria, updateExposureCriteria } = useActions(experimentLogic)
    const { closeExposureCriteriaModal } = useActions(modalsLogic)
    const { isExposureCriteriaModalOpen } = useValues(modalsLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    return (
        <LemonModal
            isOpen={isExposureCriteriaModalOpen}
            onClose={closeExposureCriteriaModal}
            width={860}
            title="Edit exposure criteria"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        type="secondary"
                        onClick={() => {
                            restoreUnmodifiedExperiment()
                            closeExposureCriteriaModal()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            updateExposureCriteria()
                            closeExposureCriteriaModal()
                        }}
                        type="primary"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex gap-4 mb-4">
                <SelectableCard
                    title="Default"
                    description={
                        <>
                            When a <LemonTag>$feature_flag_called</LemonTag> event is recorded, a user is considered{' '}
                            <strong>exposed</strong> to the experiment and included in the analysis.
                        </>
                    }
                    selected={!experiment.exposure_criteria?.exposure_config}
                    onClick={() => {
                        setExposureCriteria({
                            exposure_config: undefined,
                        })
                    }}
                />
                <SelectableCard
                    title="Custom"
                    description={
                        <>
                            If you can't rely on the <LemonTag>$feature_flag_called</LemonTag> event, you can select a
                            custom event to signal that users reached the part of your app where the experiment runs.
                            You can also filter out users you would like to exclude from the analysis.
                        </>
                    }
                    selected={!!experiment.exposure_criteria?.exposure_config}
                    onClick={() => {
                        setExposureCriteria({
                            exposure_config: {
                                kind: NodeKind.ExperimentEventExposureConfig,
                                event: '$feature_flag_called',
                                properties: [],
                            },
                        })
                    }}
                />
            </div>
            {experiment.exposure_criteria?.exposure_config && (
                <div className="mb-4">
                    <ActionFilter
                        bordered
                        filters={exposureConfigToFilter(experiment.exposure_criteria.exposure_config)}
                        setFilters={({ events }: Partial<FilterType>): void => {
                            const entity = events?.[0]
                            if (entity) {
                                setExposureCriteria({
                                    exposure_config: filterToExposureConfig(entity),
                                })
                            }
                        }}
                        typeKey="experiment-exposure-config"
                        buttonCopy="Add graph series"
                        showSeriesIndicator={true}
                        hideRename={true}
                        entitiesLimit={1}
                        mathAvailability={MathAvailability.None}
                        showNumericalPropsOnly={true}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                        propertiesTaxonomicGroupTypes={commonActionFilterProps.propertiesTaxonomicGroupTypes}
                    />
                </div>
            )}
            <div className="w-[405px]">
                <div className="mb-4">
                    <label className="block text-sm font-medium text-default mb-2">Multiple variant handling</label>
                    <LemonSelect
                        value={experiment.exposure_criteria?.multiple_variant_handling || 'exclude'}
                        onChange={(value) => {
                            setExposureCriteria({
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
                <TestAccountFilterSwitch
                    checked={(() => {
                        const val = experiment.exposure_criteria?.filterTestAccounts
                        return hasFilters ? !!val : false
                    })()}
                    onChange={(checked: boolean) => {
                        setExposureCriteria({
                            filterTestAccounts: checked,
                        })
                    }}
                    fullWidth
                />
            </div>
        </LemonModal>
    )
}
