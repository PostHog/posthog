import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
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

export function ExposureCriteriaModal(): JSX.Element {
    const { experiment, isExposureCriteriaModalOpen } = useValues(experimentLogic)
    const { closeExposureCriteriaModal, restoreUnmodifiedExperiment, setExposureCriteria, updateExposureCriteria } =
        useActions(experimentLogic)
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
                <LemonButton
                    className={`trends-metric-form__exposure-button flex-1 cursor-pointer p-4 rounded border ${
                        !experiment.exposure_criteria?.exposure_config
                            ? 'border-accent bg-accent-highlight-secondary'
                            : 'border-primary'
                    }`}
                    onClick={() => {
                        setExposureCriteria({
                            exposure_config: undefined,
                        })
                    }}
                >
                    <div className="font-semibold flex justify-between items-center">
                        <span>Default</span>
                        {!experiment.exposure_criteria?.exposure_config && (
                            <IconCheckCircle fontSize={18} color="var(--accent)" />
                        )}
                    </div>
                    <div className="text-secondary text-sm leading-relaxed mt-1">
                        Uses the number of unique users who trigger the <LemonTag>$feature_flag_called</LemonTag> event
                        as your exposure count. This is the recommended setting for most experiments, as it accurately
                        tracks variant exposure.
                    </div>
                </LemonButton>
                <LemonButton
                    className={`trends-metric-form__exposure-button flex-1 cursor-pointer p-4 rounded border ${
                        experiment.exposure_criteria?.exposure_config
                            ? 'border-accent bg-accent-highlight-secondary'
                            : 'border-primary'
                    }`}
                    onClick={() => {
                        setExposureCriteria({
                            exposure_config: {
                                kind: NodeKind.ExperimentEventExposureConfig,
                                event: '$feature_flag_called',
                                properties: [],
                            },
                        })
                    }}
                >
                    <div className="font-semibold flex justify-between items-center">
                        <span>Custom</span>
                        {experiment.exposure_criteria?.exposure_config && (
                            <IconCheckCircle fontSize={18} color="var(--accent)" />
                        )}
                    </div>
                    <div className="text-secondary text-sm leading-relaxed mt-1">
                        Define your own exposure metric for specific use cases, such as counting by sessions instead of
                        users. This gives you full control but requires careful configuration.
                    </div>
                </LemonButton>
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
        </LemonModal>
    )
}
