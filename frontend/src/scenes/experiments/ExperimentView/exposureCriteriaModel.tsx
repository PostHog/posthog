import { useActions, useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SeriesActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/types'
import { teamLogic } from 'scenes/teamLogic'

import { ExperimentExposureCriteria, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayCategory } from '~/types'

import { DefaultExposureEventNote } from 'products/experiments/frontend/components/DefaultExposureEventNote'
import { NegatedEventFilterNote } from 'products/experiments/frontend/components/NegatedEventFilterNote'
import { isLaunched } from 'products/experiments/frontend/experimentStatus'
import { WarehouseNativeExposureFields } from 'products/experiments/frontend/warehouseNative/WarehouseNativeExposureFields'
import {
    EMPTY_WAREHOUSE_NATIVE_BINDING,
    type MetricDataSources,
    getExperimentMetricDataSources,
    getExposureSourceBlockedReasons,
    getWarehouseNativeExposure,
    getWarehouseNativeExposureError,
    getWarehouseNativeMismatchError,
} from 'products/experiments/frontend/warehouseNative/warehouseNativeSources'

import { experimentLogic } from '../experimentLogic'
import { EXPOSURE_DEFAULT_EVENT, getActivationConfig } from '../exposureContract'
import { commonActionFilterProps } from '../Metrics/Selectors'
import { exposureConfigToSeries, seriesToExposureConfig } from '../utils'
import { exposureCriteriaModalLogic } from './exposureCriteriaModalLogic'

export type ExposureMode = 'default' | 'activation' | 'custom' | 'warehouse-native'

export type ExposureCriteriaModalProps = {
    onSave: (exposureCriteria: ExperimentExposureCriteria) => void
    /** Which data sources the metrics read. The wizard passes those of its draft, which `experimentLogic` does not hold. */
    metricDataSources?: MetricDataSources
}

export const EXPOSURE_CRITERIA_INTRO =
    'Exposure determines when a user enters your experiment. Only events that occur after exposure are counted in your metrics.'

export const MULTIPLE_VARIANT_HANDLING_OPTIONS = [
    { value: 'exclude', label: 'Exclude from analysis', dataAttr: 'multiple-handling-exclude' },
    { value: 'first_seen', label: 'Use first seen variant', dataAttr: 'multiple-handling-first-seen' },
] as const

export function multipleVariantHandlingHelp(handling: string | undefined | null): string {
    return handling === 'first_seen'
        ? 'Users exposed to multiple variants will be analyzed using their first seen variant.'
        : 'Users exposed to multiple variants will be excluded from the analysis (recommended).'
}

/** The description of each exposure mode, with the exposure event rendered by the caller. */
export function exposureModeDescription(mode: ExposureMode, eventTag: JSX.Element): JSX.Element {
    switch (mode) {
        case 'default':
            return (
                <>
                    When a {eventTag} event is recorded, a user is considered <strong>exposed</strong> to the experiment
                    and included in the analysis.
                </>
            )
        case 'activation':
            return (
                <>
                    Require an additional event after {eventTag}. Users enter the analysis when this event follows their
                    first exposure, and metrics count from the activation event.
                </>
            )
        case 'custom':
            return (
                <>
                    If you can't rely on the {eventTag} event, you can select a custom event to signal that users
                    reached the part of your app where the experiment runs. You can also filter which events count as
                    exposure.
                </>
            )
        case 'warehouse-native':
            return (
                <>
                    Read exposures with a SQL query that runs in your own warehouse. The metrics of the experiment then
                    run there too, and only aggregated results leave the warehouse.
                </>
            )
    }
}

export const EXPOSURE_MODE_TITLES: Record<ExposureMode, string> = {
    default: 'Default',
    activation: 'Activation event',
    custom: 'Custom',
    'warehouse-native': 'Warehouse-native',
}

export interface ExposureCriteriaModalModel {
    isOpen: boolean
    close: () => void
    save: () => void
    saveDisabledReason: string | null
    exposureCriteria: ExperimentExposureCriteria
    setExposureCriteria: (exposureCriteria: ExperimentExposureCriteria) => void
    resolvedExposureEvent: string
    hasFilters: boolean
    warehouseExposure: ReturnType<typeof getWarehouseNativeExposure>
    mode: ExposureMode
    selectMode: (mode: ExposureMode) => void
    modes: { mode: ExposureMode; blockedReason: string | null | undefined }[]
    launched: boolean
    groupTypeIndex: number | null | undefined
}

export function useExposureCriteriaModal({
    onSave,
    metricDataSources,
}: ExposureCriteriaModalProps): ExposureCriteriaModalModel {
    const { isExposureCriteriaModalOpen, exposureCriteria } = useValues(exposureCriteriaModalLogic)
    const { experiment, resolvedExposureEvent } = useValues(experimentLogic)
    const launched = isLaunched(experiment)
    const groupTypeIndex = experiment.feature_flag?.filters?.aggregation_group_type_index
    const { closeExposureCriteriaModal, setExposureCriteria } = useActions(exposureCriteriaModalLogic)

    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    const activationEventEnabled = useFeatureFlag('EXPERIMENT_ACTIVATION_EVENT')
    // getActivationConfig, not a raw field check: a stored default-sentinel exposure_config
    // still composes with activation, and the editor must classify it the way the backend does
    const isActivation = !!getActivationConfig(exposureCriteria)
    const warehouseExposure = getWarehouseNativeExposure(exposureCriteria)
    const isCustom = !isActivation && !warehouseExposure && !!exposureCriteria?.exposure_config
    // Keep an existing activation config editable even if the team is no longer flagged in
    const showActivationCard = activationEventEnabled || isActivation
    const warehouseNativeEnabled = useFeatureFlag('BIGQUERY_DIRECT_QUERY')
    // Keep an existing warehouse-native exposure editable even if the team is no longer flagged in
    const showWarehouseNativeCard = warehouseNativeEnabled || !!warehouseExposure
    const { warehouseNative: warehouseNativeBlockedReason, posthog: posthogBlockedReason } =
        getExposureSourceBlockedReasons(
            !!warehouseExposure,
            metricDataSources ?? getExperimentMetricDataSources(experiment)
        )
    // A shared metric keeps its own connection and unit, so the save cannot move it to an edited exposure
    const saveDisabledReason = warehouseExposure
        ? (getWarehouseNativeExposureError(warehouseExposure) ??
          getWarehouseNativeMismatchError(
              warehouseExposure,
              { warehouseNative: false, posthog: false },
              (experiment.saved_metrics ?? []).map((savedMetric) => savedMetric?.query)
          ))
        : null

    const mode: ExposureMode = warehouseExposure
        ? 'warehouse-native'
        : isActivation
          ? 'activation'
          : isCustom
            ? 'custom'
            : 'default'

    const selectMode = (next: ExposureMode): void => {
        // Re-picking the selected mode must not reset a configured event or query
        if (next === mode) {
            return
        }
        if (next === 'default') {
            setExposureCriteria({ ...exposureCriteria, exposure_config: undefined, activation_config: undefined })
        } else if (next === 'activation') {
            setExposureCriteria({
                ...exposureCriteria,
                exposure_config: undefined,
                activation_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: '$pageview',
                    properties: [],
                },
            })
        } else if (next === 'custom') {
            setExposureCriteria({
                ...exposureCriteria,
                exposure_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: EXPOSURE_DEFAULT_EVENT,
                    properties: [],
                },
                activation_config: undefined,
            })
        } else {
            setExposureCriteria({
                ...exposureCriteria,
                exposure_config: {
                    kind: NodeKind.ExperimentWarehouseNativeExposureConfig,
                    ...EMPTY_WAREHOUSE_NATIVE_BINDING,
                    query: '',
                },
                activation_config: undefined,
            })
        }
    }

    return {
        isOpen: isExposureCriteriaModalOpen,
        close: closeExposureCriteriaModal,
        save: () => {
            onSave(exposureCriteria)
            closeExposureCriteriaModal()
        },
        saveDisabledReason,
        exposureCriteria,
        setExposureCriteria,
        resolvedExposureEvent,
        hasFilters,
        warehouseExposure,
        mode,
        selectMode,
        modes: [
            { mode: 'default', blockedReason: posthogBlockedReason },
            ...(showActivationCard ? [{ mode: 'activation' as const, blockedReason: posthogBlockedReason }] : []),
            { mode: 'custom' as const, blockedReason: posthogBlockedReason },
            ...(showWarehouseNativeCard
                ? [{ mode: 'warehouse-native' as const, blockedReason: warehouseNativeBlockedReason }]
                : []),
        ],
        launched,
        groupTypeIndex,
    }
}

/** The editors under the mode choice: the warehouse query, or the custom or activation event. */
export function ExposureCriteriaEditors({ model }: { model: ExposureCriteriaModalModel }): JSX.Element {
    const {
        exposureCriteria,
        setExposureCriteria,
        warehouseExposure,
        resolvedExposureEvent,
        launched,
        groupTypeIndex,
        mode,
    } = model
    const isCustom = mode === 'custom'
    const isActivation = mode === 'activation'

    return (
        <>
            {warehouseExposure && (
                <div className="mb-4">
                    <WarehouseNativeExposureFields
                        exposure={warehouseExposure}
                        onChange={(exposure) => setExposureCriteria({ ...exposureCriteria, exposure_config: exposure })}
                    />
                </div>
            )}
            {isCustom && exposureCriteria?.exposure_config && (
                <div className="mb-4">
                    <SeriesActionFilter
                        bordered
                        series={exposureConfigToSeries(exposureCriteria.exposure_config)}
                        trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                        onChange={(series) => {
                            const exposureConfig = seriesToExposureConfig(series)
                            if (exposureConfig) {
                                setExposureCriteria({
                                    ...exposureCriteria,
                                    exposure_config: exposureConfig,
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
                    <DefaultExposureEventNote
                        config={exposureCriteria.exposure_config}
                        defaultExposureEvent={resolvedExposureEvent}
                    />
                    <NegatedEventFilterNote
                        config={exposureCriteria.exposure_config}
                        launched={launched}
                        groupTypeIndex={groupTypeIndex}
                    />
                </div>
            )}
            {isActivation && exposureCriteria?.activation_config && (
                <div className="mb-4">
                    <SeriesActionFilter
                        bordered
                        series={exposureConfigToSeries(exposureCriteria.activation_config)}
                        trendsDisplayCategory={ChartDisplayCategory.TimeSeries}
                        onChange={(series) => {
                            const activationConfig = seriesToExposureConfig(series)
                            if (activationConfig) {
                                setExposureCriteria({
                                    ...exposureCriteria,
                                    activation_config: activationConfig,
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
                    <NegatedEventFilterNote
                        config={exposureCriteria.activation_config}
                        launched={launched}
                        groupTypeIndex={groupTypeIndex}
                    />
                </div>
            )}
        </>
    )
}
