import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect, LemonSelectOption, LemonSelectSection, Link } from '@posthog/lemon-ui'

import { HogQLEditor } from 'lib/components/HogQLEditor/HogQLEditor'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, pluralize } from 'lib/utils'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import { FUNNEL_STEP_COUNT_LIMIT } from 'scenes/insights/EditorFilters/FunnelsQuerySteps'
import { TIME_INTERVAL_BOUNDS } from 'scenes/insights/views/Funnels/FunnelConversionWindowFilter'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownAttributionType, FunnelConversionWindowTimeUnit, StepOrderValue } from '~/types'

export const commonActionFilterProps = {
    actionsTaxonomicGroupTypes: [
        TaxonomicFilterGroupType.Events,
        TaxonomicFilterGroupType.Actions,
        TaxonomicFilterGroupType.DataWarehouse,
    ],
    propertiesTaxonomicGroupTypes: [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        TaxonomicFilterGroupType.SessionProperties,
        TaxonomicFilterGroupType.HogQLExpression,
        TaxonomicFilterGroupType.DataWarehouseProperties,
        TaxonomicFilterGroupType.DataWarehousePersonProperties,
    ],
}

// Forked from https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/insights/filters/AggregationSelect.tsx
export function FunnelAggregationSelect({
    value,
    onChange,
}: {
    value: string
    onChange: (value: string) => void
}): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { needsUpgradeForGroups, canStartUsingGroups } = useValues(groupsAccessLogic)

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
        // if (false) {
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

    baseValues.push(`properties.$session_id`)
    optionSections[0].options.push({
        value: 'properties.$session_id',
        label: `Unique sessions`,
    })
    optionSections[0].options.push({
        label: 'Custom SQL expression',
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
                                    "Enter SQL expression, such as:\n- distinct_id\n- properties.$session_id\n- concat(distinct_id, ' ', properties.$session_id)\n- if(1 < 2, 'one', 'two')"
                                }
                            />
                        </div>
                    )
                },
            },
        ],
    })

    return (
        <div className="flex items-center w-full gap-2">
            <span>Aggregating by</span>
            <LemonSelect
                className="flex-1"
                value={value}
                onChange={onChange}
                options={optionSections}
                dropdownMatchSelectWidth={false}
            />
        </div>
    )
}

// Forked from https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/insights/views/Funnels/FunnelConversionWindowFilter.tsx
export function FunnelConversionWindowFilter({
    funnelWindowInterval,
    funnelWindowIntervalUnit,
    onFunnelWindowIntervalChange,
    onFunnelWindowIntervalUnitChange,
}: {
    funnelWindowInterval: number | undefined
    funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | undefined
    onFunnelWindowIntervalChange: (funnelWindowInterval: number | undefined) => void
    onFunnelWindowIntervalUnitChange: (funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit) => void
}): JSX.Element {
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
                    value={funnelWindowInterval}
                    onChange={onFunnelWindowIntervalChange}
                />
                <LemonSelect
                    dropdownMatchSelectWidth={false}
                    value={funnelWindowIntervalUnit}
                    onChange={onFunnelWindowIntervalUnitChange}
                    options={options}
                />
            </div>
        </div>
    )
}

// Forked from https://github.com/PostHog/posthog/blob/master/frontend/src/scenes/insights/EditorFilters/AttributionFilter.tsx
export function FunnelAttributionSelect({
    value,
    onChange,
    stepsLength,
}: {
    value: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}`
    onChange: (value: BreakdownAttributionType | `${BreakdownAttributionType.Step}/${number}`) => void
    stepsLength: number
}): JSX.Element {
    const funnelOrderType = undefined

    return (
        <div className="flex items-center w-full gap-2">
            <div className="flex">
                <span>Attribution type</span>
                <Tooltip
                    closeDelayMs={200}
                    title={
                        <div className="deprecated-space-y-2">
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
                    <IconInfo className="text-xl text-secondary shrink-0 ml-1" />
                </Tooltip>
            </div>
            <LemonSelect
                value={value}
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
                                value: `${BreakdownAttributionType.Step}/${stepIndex}` as const,
                                label: `Step ${stepIndex + 1}`,
                                hidden: stepIndex >= stepsLength,
                            })),
                        hidden: funnelOrderType === StepOrderValue.UNORDERED,
                    },
                ]}
                onChange={onChange}
                dropdownMaxContentWidth={true}
                data-attr="breakdown-attributions"
            />
        </div>
    )
}
