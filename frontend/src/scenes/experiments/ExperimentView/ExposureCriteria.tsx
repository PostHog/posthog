import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, LemonTag } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { teamLogic } from 'scenes/teamLogic'

import { ExperimentExposureCriteria, NodeKind } from '~/queries/schema/schema-general'
import { FilterType } from '~/types'

import { SelectableCard } from '../components/SelectableCard'
import { experimentLogic } from '../experimentLogic'
import { EXPOSURE_DEFAULT_EVENT, getActivationConfig } from '../exposureContract'
import { commonActionFilterProps } from '../Metrics/Selectors'
import { exposureConfigToFilter, filterToExposureConfig } from '../utils'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

type ExposureCriteriaModalProps = {
    onSave: (exposureCriteria: ExperimentExposureCriteria) => void
}

export function ExposureCriteriaModal({ onSave }: ExposureCriteriaModalProps): JSX.Element | null {
    const { isExposureCriteriaModalOpen, exposureCriteria } = useValues(exposureCriteriaModalLogic)
    const { resolvedExposureEvent } = useValues(experimentLogic)
    const { closeExposureCriteriaModal, setExposureCriteria } = useActions(exposureCriteriaModalLogic)

    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    const activationEventEnabled = useFeatureFlag('EXPERIMENT_ACTIVATION_EVENT')
    // getActivationConfig, not a raw field check: a stored default-sentinel exposure_config
    // still composes with activation, and the editor must classify it the way the backend does
    const isActivation = !!getActivationConfig(exposureCriteria)
    const isCustom = !isActivation && !!exposureCriteria?.exposure_config
    // Keep an existing activation config editable even if the team is no longer flagged in
    const showActivationCard = activationEventEnabled || isActivation

    return (
        <LemonModal
            isOpen={isExposureCriteriaModalOpen}
            onClose={closeExposureCriteriaModal}
            width={860}
            title="Edit exposure criteria"
            zIndex="1169"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        type="secondary"
                        onClick={() => {
                            closeExposureCriteriaModal()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            onSave(exposureCriteria)
                            closeExposureCriteriaModal()
                        }}
                        type="primary"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="text-secondary text-sm mb-4">
                Exposure determines when a user enters your experiment. Only events that occur after exposure are
                counted in your metrics.
            </div>
            <div className="flex gap-4 mb-4">
                <SelectableCard
                    title="Default"
                    description={
                        <>
                            When a <LemonTag>{resolvedExposureEvent}</LemonTag> event is recorded, a user is considered{' '}
                            <strong>exposed</strong> to the experiment and included in the analysis.
                        </>
                    }
                    selected={!isCustom && !isActivation}
                    onClick={() => {
                        setExposureCriteria({
                            ...exposureCriteria,
                            exposure_config: undefined,
                            activation_config: undefined,
                        })
                    }}
                />
                {showActivationCard && (
                    <SelectableCard
                        title="Activation event"
                        description={
                            <>
                                Require an additional event after <LemonTag>{resolvedExposureEvent}</LemonTag>. Users
                                enter the analysis when this event follows their first exposure, and metrics count from
                                the activation event.
                            </>
                        }
                        selected={isActivation}
                        onClick={() => {
                            // Re-clicking the selected card must not reset a configured event
                            if (isActivation) {
                                return
                            }
                            setExposureCriteria({
                                ...exposureCriteria,
                                exposure_config: undefined,
                                activation_config: {
                                    kind: NodeKind.ExperimentEventExposureConfig,
                                    event: '$pageview',
                                    properties: [],
                                },
                            })
                        }}
                    />
                )}
                <SelectableCard
                    title="Custom"
                    description={
                        <>
                            If you can't rely on the <LemonTag>{resolvedExposureEvent}</LemonTag> event, you can select
                            a custom event to signal that users reached the part of your app where the experiment runs.
                            You can also filter out users you would like to exclude from the analysis.
                        </>
                    }
                    selected={isCustom}
                    onClick={() => {
                        // Re-clicking the selected card must not reset a configured event
                        if (isCustom) {
                            return
                        }
                        setExposureCriteria({
                            ...exposureCriteria,
                            exposure_config: {
                                kind: NodeKind.ExperimentEventExposureConfig,
                                event: EXPOSURE_DEFAULT_EVENT,
                                properties: [],
                            },
                            activation_config: undefined,
                        })
                    }}
                />
            </div>
            {isCustom && exposureCriteria?.exposure_config && (
                <div className="mb-4">
                    <ActionFilter
                        bordered
                        filters={exposureConfigToFilter(exposureCriteria.exposure_config)}
                        setFilters={({ events, actions }: Partial<FilterType>): void => {
                            const entity = events?.[0] || actions?.[0]
                            if (entity) {
                                setExposureCriteria({
                                    ...exposureCriteria,
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
                        {...commonActionFilterProps}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                    />
                </div>
            )}
            {isActivation && exposureCriteria?.activation_config && (
                <div className="mb-4">
                    <ActionFilter
                        bordered
                        filters={exposureConfigToFilter(exposureCriteria.activation_config)}
                        setFilters={({ events, actions }: Partial<FilterType>): void => {
                            const entity = events?.[0] || actions?.[0]
                            if (entity) {
                                setExposureCriteria({
                                    ...exposureCriteria,
                                    activation_config: filterToExposureConfig(entity),
                                })
                            }
                        }}
                        typeKey="experiment-activation-config"
                        buttonCopy="Add activation event"
                        showSeriesIndicator={true}
                        hideRename={true}
                        entitiesLimit={1}
                        mathAvailability={MathAvailability.None}
                        showNumericalPropsOnly={true}
                        {...commonActionFilterProps}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                    />
                </div>
            )}
            <div className="w-[405px]">
                <div className="mb-4">
                    <label className="block text-sm font-medium text-default mb-2">Multiple variant handling</label>
                    <LemonSelect
                        value={exposureCriteria?.multiple_variant_handling || 'exclude'}
                        onChange={(value) => {
                            setExposureCriteria({
                                ...exposureCriteria,
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
                        {exposureCriteria?.multiple_variant_handling === 'first_seen' &&
                            'Users exposed to multiple variants will be analyzed using their first seen variant.'}
                        {(!exposureCriteria?.multiple_variant_handling ||
                            exposureCriteria?.multiple_variant_handling === 'exclude') &&
                            'Users exposed to multiple variants will be excluded from the analysis (recommended).'}
                    </div>
                </div>
                <TestAccountFilterSwitch
                    checked={(() => {
                        const val = exposureCriteria?.filterTestAccounts
                        return hasFilters ? !!val : false
                    })()}
                    onChange={(checked: boolean) => {
                        setExposureCriteria({
                            ...exposureCriteria,
                            filterTestAccounts: checked,
                        })
                    }}
                    fullWidth
                />
            </div>
        </LemonModal>
    )
}
