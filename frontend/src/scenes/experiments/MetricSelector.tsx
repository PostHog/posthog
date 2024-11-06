import './Experiment.scss'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSelectOption, LemonSelectSection, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { EXPERIMENT_DEFAULT_DURATION } from 'lib/constants'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { groupsModel } from '~/models/groupsModel'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { FunnelsFilter, NodeKind } from '~/queries/schema'
import {
    BreakdownAttributionType,
    FilterType,
    FunnelConversionWindowTimeUnit,
    FunnelsFilterType,
    InsightType,
    StepOrderValue,
} from '~/types'
import { experimentLogic } from './experimentLogic'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { FUNNEL_STEP_COUNT_LIMIT } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'
import { teamLogic } from 'scenes/teamLogic'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { getHogQLValue } from 'scenes/insights/filters/AggregationSelect'

export interface MetricSelectorProps {
    forceTrendExposureMetric?: boolean
}

export function MetricSelector({ forceTrendExposureMetric }: MetricSelectorProps): JSX.Element {
    const { experiment, experimentInsightType, isExperimentRunning } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)
    const isTrends = experimentInsightType === InsightType.TRENDS

    return (
        <>
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Insight Type</span>
                <LemonSelect
                    data-attr="metrics-selector"
                    value={experimentInsightType}
                    onChange={(newInsightType) => {
                        // HANDLE FLAG

                        setExperiment({
                            filters: {
                                ...experiment.filters,
                                insight: newInsightType,
                            },
                        })
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                    disabledReason={forceTrendExposureMetric ? 'Exposure metric can only be a trend graph' : undefined}
                />
            </div>

            <div>
                <br />
            </div>
            <>
                <ActionFilter
                    bordered
                    filters={experiment.filters}
                    setFilters={({ actions, events, data_warehouse }: Partial<FilterType>): void => {
                        // HANDLE FLAG

                        if (actions?.length) {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    actions,
                                    events: undefined,
                                    data_warehouse: undefined,
                                },
                            })
                        } else if (events?.length) {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    events,
                                    actions: undefined,
                                    data_warehouse: undefined,
                                },
                            })
                        } else if (data_warehouse?.length) {
                            setExperiment({
                                filters: {
                                    ...experiment.filters,
                                    data_warehouse,
                                    actions: undefined,
                                    events: undefined,
                                },
                            })
                        }
                    }}
                    typeKey="experiment-metric"
                    mathAvailability={isTrends ? undefined : MathAvailability.None}
                    buttonCopy={isTrends ? 'Add graph series' : 'Add funnel step'}
                    showSeriesIndicator={true}
                    entitiesLimit={isTrends ? 1 : undefined}
                    seriesIndicatorType={isTrends ? undefined : 'numeric'}
                    sortable={isTrends ? undefined : true}
                    showNestedArrow={isTrends ? undefined : true}
                    showNumericalPropsOnly={isTrends}
                    actionsTaxonomicGroupTypes={[
                        TaxonomicFilterGroupType.Events,
                        TaxonomicFilterGroupType.Actions,
                        TaxonomicFilterGroupType.DataWarehouse,
                    ]}
                    propertiesTaxonomicGroupTypes={[
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.EventFeatureFlags,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.Elements,
                        TaxonomicFilterGroupType.HogQLExpression,
                        TaxonomicFilterGroupType.DataWarehouseProperties,
                        TaxonomicFilterGroupType.DataWarehousePersonProperties,
                    ]}
                />
                <div className="mt-4 space-y-4">
                    {experimentInsightType === InsightType.FUNNELS && (
                        <>
                            <div className="flex items-center w-full gap-2">
                                <span>Aggregating by</span>
                                <FunnelAggregationSelect
                                    aggregation_group_type_index={
                                        (experiment.filters as FunnelsFilterType).aggregation_group_type_index ??
                                        undefined
                                    }
                                    onChange={(newValue) => {
                                        // HANDLE FLAG

                                        // the field to set is either aggregation_group_type_index or funnel_aggregate_by_hogql
                                        // how do we determine this?

                                        console.log(newValue)
                                        setExperiment({
                                            filters: {
                                                ...experiment.filters,
                                                aggregation_group_type_index: newValue,
                                            },
                                        })
                                    }}
                                />
                            </div>
                            <FunnelConversionWindowFilter />
                            <FunnelAttributionSelect />
                        </>
                    )}
                    <InsightTestAccountFilter />
                </div>
            </>
            {isExperimentRunning && (
                <LemonBanner type="info" className="mt-3 mb-3">
                    Preview insights are generated based on {EXPERIMENT_DEFAULT_DURATION} days of data. This can cause a
                    mismatch between the preview and the actual results.
                </LemonBanner>
            )}

            <div className="mt-4">
                <Query
                    query={{
                        kind: NodeKind.InsightVizNode,
                        source: filtersToQueryNode(experiment.filters),
                        showTable: false,
                        showLastComputation: true,
                        showLastComputationRefresh: false,
                    }}
                    readOnly
                />
            </div>
        </>
    )
}

export function FunnelAggregationSelect({
    aggregation_group_type_index,
    onChange,
}: {
    aggregation_group_type_index: number | undefined
    onChange: (value: number | undefined) => void
}): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { needsUpgradeForGroups, canStartUsingGroups } = useValues(groupsAccessLogic)

    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)

    const UNIQUE_USERS = 'person_id'
    const baseValues = [UNIQUE_USERS]
    const optionSections: LemonSelectSection<string>[] = [
        {
            title: 'Event Aggregation',
            options: [
                {
                    value: UNIQUE_USERS,
                    label: 'Unique users',
                },
            ],
        },
    ]
    if (needsUpgradeForGroups || canStartUsingGroups) {
        optionSections[0].footer = <GroupIntroductionFooter needsUpgrade={needsUpgradeForGroups} />
    } else {
        Array.from(groupTypes.values()).forEach((groupType) => {
            baseValues.push(`$group_${groupType.group_type_index}`)
            optionSections[0].options.push({
                value: `$group_${groupType.group_type_index}`,
                label: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
            })
        })
    }

    const value = getHogQLValue(aggregation_group_type_index)

    baseValues.push(`properties.$session_id`)
    optionSections[0].options.push({
        value: 'properties.$session_id',
        label: `Unique sessions`,
    })
    optionSections[0].options.push({
        label: 'Custom HogQL expression',
        options: [
            {
                // This is a bit of a hack so that the HogQL option is only highlighted as active when the user has
                // set a custom value (because actually _all_ the options are HogQL)
                value: !value || baseValues.includes(value) ? '' : value,
                label: <span className="font-mono">{value}</span>,
                labelInMenu: function CustomHogQLOptionWrapped({ onSelect }) {
                    return (
                        // eslint-disable-next-line react/forbid-dom-props
                        <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                            <HogQLEditor
                                onChange={onSelect}
                                value={value}
                                placeholder={
                                    "Enter HogQL expression, such as:\n- distinct_id\n- properties.$session_id\n- concat(distinct_id, ' ', properties.$session_id)\n- if(1 < 2, 'one', 'two')"
                                }
                            />
                        </div>
                    )
                },
            },
        ],
    })

    return (
        <LemonSelect
            className="flex-1"
            value={value}
            onChange={onChange}
            options={optionSections}
            dropdownMatchSelectWidth={false}
        />
    )
}

export function FunnelConversionWindowFilter(): JSX.Element {
    const TIME_INTERVAL_BOUNDS: Record<FunnelConversionWindowTimeUnit, number[]> = {
        [FunnelConversionWindowTimeUnit.Second]: [1, 3600],
        [FunnelConversionWindowTimeUnit.Minute]: [1, 1440],
        [FunnelConversionWindowTimeUnit.Hour]: [1, 24],
        [FunnelConversionWindowTimeUnit.Day]: [1, 365],
        [FunnelConversionWindowTimeUnit.Week]: [1, 53],
        [FunnelConversionWindowTimeUnit.Month]: [1, 12],
    }

    const DEFAULT_FUNNEL_WINDOW_INTERVAL = 14

    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)

    const {
        funnelWindowInterval = DEFAULT_FUNNEL_WINDOW_INTERVAL,
        funnelWindowIntervalUnit = FunnelConversionWindowTimeUnit.Day,
    } = {} as FunnelsFilter

    const options: LemonSelectOption<FunnelConversionWindowTimeUnit>[] = Object.keys(TIME_INTERVAL_BOUNDS).map(
        (unit) => ({
            label: capitalizeFirstLetter(pluralize(funnelWindowInterval ?? 7, unit, `${unit}s`, false)),
            value: unit as FunnelConversionWindowTimeUnit,
        })
    )
    const intervalBounds = TIME_INTERVAL_BOUNDS[funnelWindowIntervalUnit ?? FunnelConversionWindowTimeUnit.Day]

    return (
        <div className="flex items-center gap-2">
            <span className="flex whitespace-nowrap">
                Conversion window limit
                <Tooltip
                    title={
                        <>
                            <b>Recommended!</b> Limit to participants that converted within a specific time frame.
                            Participants that do not convert in this time frame will be considered as drop-offs.
                        </>
                    }
                >
                    <IconInfo className="w-4 info-indicator" />
                </Tooltip>
            </span>
            <div className="flex items-center gap-2">
                <LemonInput
                    type="number"
                    className="max-w-20"
                    fullWidth={false}
                    min={intervalBounds[0]}
                    max={intervalBounds[1]}
                    value={(experiment.filters as FunnelsFilterType).funnel_window_interval}
                    onChange={(funnelWindowInterval) => {
                        setExperiment({
                            filters: {
                                ...experiment.filters,
                                funnel_window_interval: Number(funnelWindowInterval),
                            },
                        })
                    }}
                />
                <LemonSelect
                    dropdownMatchSelectWidth={false}
                    value={(experiment.filters as FunnelsFilterType).funnel_window_interval_unit}
                    onChange={(funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | null) => {
                        // HANDLE FLAG

                        setExperiment({
                            filters: {
                                ...experiment.filters,
                                funnel_window_interval_unit: funnelWindowIntervalUnit || undefined,
                            },
                        })
                    }}
                    options={options}
                />
            </div>
        </div>
    )
}

export function FunnelAttributionSelect(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)

    const breakdownAttributionType = (experiment.filters as FunnelsFilterType).breakdown_attribution_type
    const breakdownAttributionValue = (experiment.filters as FunnelsFilterType).breakdown_attribution_value
    const funnelOrderType = undefined
    const stepsLength = Math.max(
        experiment.filters.actions?.length ?? 0,
        experiment.filters.events?.length ?? 0,
        experiment.filters.data_warehouse?.length ?? 0
    )

    const currentValue: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}` =
        !breakdownAttributionType
            ? BreakdownAttributionType.FirstTouch
            : breakdownAttributionType === BreakdownAttributionType.Step
            ? `${breakdownAttributionType}/${breakdownAttributionValue || 0}`
            : breakdownAttributionType

    return (
        <div className="flex items-center w-full gap-2">
            <div className="flex">
                <span>Attribution type</span>
                <Tooltip
                    closeDelayMs={200}
                    title={
                        <div className="space-y-2">
                            <div>
                                When breaking down funnels, it's possible that the same properties don't exist on every
                                event. For example, if you want to break down by browser on a funnel that contains both
                                frontend and backend events.
                            </div>
                            <div>
                                In this case, you can choose from which step the properties should be selected from by
                                modifying the attribution type. There are four modes to choose from:
                            </div>
                            <ul className="list-disc pl-4">
                                <li>First touchpoint: the first property value seen in any of the steps is chosen.</li>
                                <li>Last touchpoint: the last property value seen from all steps is chosen.</li>
                                <li>
                                    All steps: the property value must be seen in all steps to be considered in the
                                    funnel.
                                </li>
                                <li>Specific step: only the property value seen at the selected step is chosen.</li>
                            </ul>
                            <div>
                                Read more in the{' '}
                                <Link to="https://posthog.com/docs/product-analytics/funnels#attribution-types">
                                    documentation.
                                </Link>
                            </div>
                        </div>
                    }
                >
                    <IconInfo className="text-xl text-muted-alt shrink-0 ml-1" />
                </Tooltip>
            </div>
            <LemonSelect
                value={currentValue}
                placeholder="Attribution"
                options={[
                    { value: BreakdownAttributionType.FirstTouch, label: 'First touchpoint' },
                    { value: BreakdownAttributionType.LastTouch, label: 'Last touchpoint' },
                    { value: BreakdownAttributionType.AllSteps, label: 'All steps' },
                    {
                        value: BreakdownAttributionType.Step,
                        label: 'Any step',
                        hidden: funnelOrderType !== StepOrderValue.UNORDERED,
                    },
                    {
                        label: 'Specific step',
                        options: Array(FUNNEL_STEP_COUNT_LIMIT)
                            .fill(null)
                            .map((_, stepIndex) => ({
                                value: `${BreakdownAttributionType.Step}/${stepIndex}`,
                                label: `Step ${stepIndex + 1}`,
                                hidden: stepIndex >= stepsLength,
                            })),
                        hidden: funnelOrderType === StepOrderValue.UNORDERED,
                    },
                ]}
                onChange={(value) => {
                    const [breakdownAttributionType, breakdownAttributionValue] = (value || '').split('/')
                    if (value) {
                        // HANDLE FLAG

                        setExperiment({
                            filters: {
                                ...experiment.filters,
                                breakdown_attribution_type: breakdownAttributionType as BreakdownAttributionType,
                                breakdown_attribution_value: breakdownAttributionValue
                                    ? parseInt(breakdownAttributionValue)
                                    : 0,
                            },
                        })
                    }
                }}
                dropdownMaxContentWidth={true}
                data-attr="breakdown-attributions"
            />
        </div>
    )
}

export function InsightTestAccountFilter(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    return (
        <TestAccountFilterSwitch
            checked={hasFilters ? !!experiment.filters.filter_test_accounts : false}
            onChange={(checked: boolean) => {
                // HANDLE FLAG

                setExperiment({
                    filters: {
                        ...experiment.filters,
                        filter_test_accounts: checked,
                    },
                })
            }}
            fullWidth
        />
    )
}
