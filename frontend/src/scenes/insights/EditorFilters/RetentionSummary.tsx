import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { toast } from 'react-toastify'
import { AggregationSelect } from 'scenes/insights/filters/AggregationSelect'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import {
    dateOptionPlurals,
    dateOptions,
    retentionOptionDescriptions,
    retentionOptions,
} from 'scenes/retention/constants'

import { groupsModel } from '~/models/groupsModel'
import { EditorFilterProps, FilterType, RetentionType } from '~/types'

import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'

export function RetentionSummary({ insightProps }: EditorFilterProps): JSX.Element {
    const { showGroupsOptions } = useValues(groupsModel)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { targetEntity, returningEntity, retentionType, totalIntervals, period } = retentionFilter || {}

    return (
        <div className="space-y-2" data-attr="retention-summary">
            <div className="flex items-center">
                Show
                {showGroupsOptions ? (
                    <AggregationSelect className="mx-2" insightProps={insightProps} hogqlAvailable={false} />
                ) : (
                    <b> Unique users </b>
                )}
                who performed
            </div>
            <div className="flex items-center">
                event or action
                <span className="mx-2">
                    <ActionFilter
                        entitiesLimit={1}
                        mathAvailability={MathAvailability.None}
                        hideFilter
                        hideRename
                        buttonCopy="Add graph series"
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
                </span>
                <LemonSelect
                    options={Object.entries(retentionOptions).map(([key, value]) => ({
                        label: value,
                        value: key,
                        element: (
                            <>
                                {value}
                                <Tooltip placement="right" title={retentionOptionDescriptions[key]}>
                                    <IconInfo className="info-indicator" />
                                </Tooltip>
                            </>
                        ),
                    }))}
                    value={retentionType ? retentionOptions[retentionType] : undefined}
                    onChange={(value): void => updateInsightFilter({ retentionType: value as RetentionType })}
                    dropdownMatchSelectWidth={false}
                />
            </div>
            <div className="flex items-center">
                in the last
                <LemonInput
                    type="number"
                    className="ml-2 w-20"
                    defaultValue={(totalIntervals ?? 11) - 1}
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
                                    The maximum number of {dateOptionPlurals[period || 'Day']} is <strong>31</strong>
                                </>
                            )
                        }
                        target.value = newValue.toString()
                        updateInsightFilter({ totalIntervals: (newValue || 0) + 1 })
                    }}
                />
                <LemonSelect
                    className="mx-2"
                    value={period}
                    onChange={(value): void => updateInsightFilter({ period: value ? value : undefined })}
                    options={dateOptions.map((period) => ({
                        value: period,
                        label: dateOptionPlurals[period] || period,
                    }))}
                    dropdownMatchSelectWidth={false}
                />
                and then came back to perform
            </div>
            <div className="flex items-center">
                event or action
                <span className="mx-2">
                    <ActionFilter
                        entitiesLimit={1}
                        mathAvailability={MathAvailability.None}
                        hideFilter
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
                </span>
                on any of the next {dateOptionPlurals[period ?? 'Day']}.
            </div>
            <div>
                <p className="text-muted mt-4">
                    Want to learn more about retention?{' '}
                    <Link
                        to="https://posthog.com/docs/features/retention?utm_campaign=learn-more-horizontal&utm_medium=in-product"
                        target="_blank"
                        className="inline-flex items-center"
                    >
                        Go to docs
                    </Link>
                </p>
            </div>
        </div>
    )
}
