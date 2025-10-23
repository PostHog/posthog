import { useActions, useValues } from 'kea'
import { Fragment, useEffect } from 'react'
import { toast } from 'react-toastify'

import { IconInfo } from '@posthog/icons'
import { LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { AggregationSelect } from 'scenes/insights/filters/AggregationSelect'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    dateOptionPlurals,
    dateOptions,
    retentionOptionDescriptions,
    retentionOptions,
} from 'scenes/retention/constants'
import { retentionLogic } from 'scenes/retention/retentionLogic'

import { groupsModel } from '~/models/groupsModel'
import { EditorFilterProps, FilterType, RetentionPeriod, RetentionType } from '~/types'

import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'

const MAX_BRACKETS = 30
const MAX_RANGE = 1000

function CustomBrackets({ insightProps }: { insightProps: EditorFilterProps['insightProps'] }): JSX.Element {
    const { retentionFilter, localCustomBrackets } = useValues(retentionLogic(insightProps))
    const { updateInsightFilter, updateLocalCustomBracket, setLocalCustomBrackets } = useActions(
        retentionLogic(insightProps)
    )
    const { period } = retentionFilter || {}

    useEffect(() => {
        if (retentionFilter?.retentionCustomBrackets) {
            setLocalCustomBrackets([...(retentionFilter.retentionCustomBrackets || []), ''])
        }
    }, [retentionFilter?.retentionCustomBrackets])

    const getBracketLabel = (index: number): string => {
        const numericBrackets = localCustomBrackets
            .filter((b) => b !== '')
            .map((b) => (typeof b === 'string' ? parseInt(b, 10) : b))
            .filter((b): b is number => !isNaN(b) && b > 0)

        const unit = dateOptionPlurals[period || 'Day'].toLowerCase().slice(0, -1)
        let cumulativeTotal = 1
        for (let i = 0; i < index; i++) {
            cumulativeTotal += numericBrackets[i] || 0
        }

        const start = cumulativeTotal
        const end = cumulativeTotal + (numericBrackets[index] || 0) - 1

        if (start === end) {
            return `${unit} ${start}`
        }
        return `${unit} ${start}-${end}`
    }

    const totalRange = (retentionFilter?.retentionCustomBrackets || []).reduce(
        (acc: number, val: number) => acc + val,
        0
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <div>Bracket By</div>
                <LemonSelect
                    value={period}
                    onChange={(value): void => {
                        updateInsightFilter({ period: value ? value : undefined })
                    }}
                    options={dateOptions.map((period) => ({
                        value: period,
                        label: dateOptionPlurals[period] || period,
                    }))}
                    dropdownMatchSelectWidth={false}
                />
            </div>
            {localCustomBrackets.map((bracket, index) => {
                if (index >= MAX_BRACKETS) {
                    return null
                }
                return (
                    <div key={index} className="flex items-center gap-2">
                        <div>{index + 1}st Bracket</div>
                        <LemonInput
                            type="number"
                            className="w-20"
                            value={typeof bracket === 'number' ? bracket : undefined}
                            min={1}
                            onChange={(value) => {
                                updateLocalCustomBracket(index, value)
                            }}
                        />
                        {bracket !== '' && <div>{getBracketLabel(index)}</div>}
                    </div>
                )
            })}
            {totalRange > MAX_RANGE && <div className="text-xs text-danger">Total range is too large.</div>}
        </div>
    )
}

export function RetentionCondition({ insightProps }: EditorFilterProps): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)
    const { retentionFilter, dateRange } = useValues(retentionLogic(insightProps))
    const { updateInsightFilter, updateDateRange } = useActions(retentionLogic(insightProps))
    const { targetEntity, returningEntity, retentionType, totalIntervals, period, retentionCustomBrackets } =
        retentionFilter || {}

    return (
        <div className="deprecated-space-y-3 mb-4" data-attr="retention-condition">
            <div className="flex items-center">
                For
                {showGroupsOptions ? (
                    <AggregationSelect className="mx-2" insightProps={insightProps} hogqlAvailable={false} />
                ) : (
                    <b> Unique users </b>
                )}
            </div>
            <div>who performed</div>
            <ActionFilter
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                hideRename
                filters={{ events: [targetEntity] } as FilterType} // retention filters use target and returning entity instead of events
                setFilters={(newFilters: FilterType) => {
                    if (newFilters.events && newFilters.events.length > 0) {
                        updateInsightFilter({ targetEntity: newFilters.events[0] })
                    } else if (newFilters.actions && newFilters.actions.length > 0) {
                        updateInsightFilter({ targetEntity: newFilters.actions[0] })
                    } else {
                        updateInsightFilter({ targetEntity: undefined })
                    }
                }}
                typeKey={`${keyForInsightLogicProps('new')(insightProps)}-targetEntity`}
            />
            <LemonSelect
                options={Object.entries(retentionOptions).map(([key, value]) => ({
                    value: key,
                    label: value,
                    labelInMenu: (
                        <div className="flex items-center justify-between w-full">
                            <Tooltip
                                placement="right"
                                title={retentionOptionDescriptions[key as keyof typeof retentionOptionDescriptions]}
                            >
                                <div className="flex items-center gap-1">
                                    <span>{value}</span>
                                    <IconInfo className="info-indicator" />
                                </div>
                            </Tooltip>
                        </div>
                    ),
                }))}
                value={retentionType}
                onChange={(value): void => updateInsightFilter({ retentionType: value as RetentionType })}
                dropdownMatchSelectWidth={false}
            />

            <div>and then returned to perform</div>
            <ActionFilter
                entitiesLimit={1}
                mathAvailability={MathAvailability.None}
                hideRename
                buttonCopy="Add graph series"
                filters={{ events: [returningEntity] } as FilterType}
                setFilters={(newFilters: FilterType) => {
                    if (newFilters.events && newFilters.events.length > 0) {
                        updateInsightFilter({ returningEntity: newFilters.events[0] })
                    } else if (newFilters.actions && newFilters.actions.length > 0) {
                        updateInsightFilter({ returningEntity: newFilters.actions[0] })
                    } else {
                        updateInsightFilter({ returningEntity: undefined })
                    }
                }}
                typeKey={`${keyForInsightLogicProps('new')(insightProps)}-returningEntity`}
            />
            <div className="flex items-center gap-2">
                {!retentionCustomBrackets ? (
                    <Fragment>
                        <div>during the next</div>
                        <LemonInput
                            type="number"
                            className="ml-2 w-20"
                            defaultValue={(totalIntervals ?? 7) - 1}
                            min={1}
                            max={31}
                            onBlur={({ target }) => {
                                let newValue = Number(target.value)
                                if (newValue > 31) {
                                    // See if just the first two numbers are under 31 (when someone mashed keys)
                                    newValue = Number(target.value.substring(0, 2))
                                    if (newValue > 31) {
                                        newValue = 10
                                    }
                                    toast.warn(
                                        <>
                                            The maximum number of {dateOptionPlurals[period || 'Day']} is{' '}
                                            <strong>31</strong>
                                        </>
                                    )
                                }
                                target.value = newValue.toString()
                                updateInsightFilter({ totalIntervals: (newValue || 0) + 1 })
                                if (!dateRange) {
                                    // if we haven't updated date range before changing interval type
                                    // set date range
                                    updateDateRange({
                                        date_from: `-7${(period ?? RetentionPeriod.Day)?.toLowerCase().charAt(0)}`,
                                        date_to: `now`,
                                    })
                                }
                            }}
                        />
                        <LemonSelect
                            value={period}
                            onChange={(value): void => {
                                updateInsightFilter({ period: value ? value : undefined })
                                // reset date range when we change interval type
                                updateDateRange({
                                    date_from: `-7${(value ?? RetentionPeriod.Day)?.toLowerCase().charAt(0)}`,
                                    date_to: `now`,
                                })
                            }}
                            options={dateOptions.map((period) => ({
                                value: period,
                                label: dateOptionPlurals[period] || period,
                            }))}
                            dropdownMatchSelectWidth={false}
                        />
                    </Fragment>
                ) : null}
            </div>
            <LemonCheckbox
                label="Use custom return ranges"
                checked={!!retentionCustomBrackets}
                onChange={(checked) => {
                    if (checked) {
                        updateInsightFilter({ retentionCustomBrackets: [1, 3, 5] })
                    } else {
                        updateInsightFilter({ retentionCustomBrackets: undefined })
                    }
                }}
            />
            {retentionCustomBrackets ? <CustomBrackets insightProps={insightProps} /> : null}
        </div>
    )
}
