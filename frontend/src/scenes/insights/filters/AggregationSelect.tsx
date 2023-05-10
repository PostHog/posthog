import { useActions, useValues } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import { LemonButton, LemonButtonWithDropdown, LemonTextArea } from '@posthog/lemon-ui'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { InsightLogicProps } from '~/types'
import { insightLogic } from '../insightLogic'
import { isFunnelsQuery, isInsightQueryNode } from '~/queries/utils'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { FunnelsQuery } from '~/queries/schema'
import { isFunnelsFilter } from 'scenes/insights/sharedUtils'
import { useEffect, useState } from 'react'

type AggregationSelectProps = {
    insightProps: InsightLogicProps
    className?: string
    hogqlAvailable?: boolean
    value?: string
}

function getHogQLValue(groupIndex?: number, aggregationQuery?: string): string {
    if (groupIndex !== undefined) {
        return `$group_${groupIndex}`
    } else if (aggregationQuery) {
        return aggregationQuery
    } else {
        return UNIQUE_USERS
    }
}

function hogQLToFilterValue(value?: string): { groupIndex?: number; aggregationQuery?: string } {
    if (value?.match(/^\$group_[0-9]+$/)) {
        return { groupIndex: parseInt(value.replace('$group_', '')) }
    } else if (value === 'person_id') {
        return {}
    } else {
        return { aggregationQuery: value }
    }
}

export function AggregationSelectDataExploration({
    insightProps,
    className,
    hogqlAvailable,
}: AggregationSelectProps): JSX.Element | null {
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    if (!isInsightQueryNode(querySource)) {
        return null
    }

    const value = getHogQLValue(
        querySource.aggregation_group_type_index,
        isFunnelsQuery(querySource) ? querySource.funnelsFilter?.funnel_aggregate_by_hogql : undefined
    )

    return (
        <AggregationSelectComponent
            className={className}
            hogqlAvailable={hogqlAvailable}
            value={value}
            onChange={(value) => {
                const { aggregationQuery, groupIndex } = hogQLToFilterValue(value)
                if (isFunnelsQuery(querySource)) {
                    updateQuerySource({
                        aggregation_group_type_index: groupIndex,
                        funnelsFilter: { ...querySource.funnelsFilter, funnel_aggregate_by_hogql: aggregationQuery },
                    } as FunnelsQuery)
                } else {
                    updateQuerySource({ aggregation_group_type_index: groupIndex } as FunnelsQuery)
                }
            }}
        />
    )
}

export function AggregationSelect({ insightProps, className, hogqlAvailable }: AggregationSelectProps): JSX.Element {
    const { filters } = useValues(insightLogic(insightProps))
    const { setFilters } = useActions(funnelLogic(insightProps))

    const value = getHogQLValue(
        filters.aggregation_group_type_index,
        isFunnelsFilter(filters) ? filters.funnel_aggregate_by_hogql : undefined
    )

    return (
        <AggregationSelectComponent
            className={className}
            value={value}
            hogqlAvailable={hogqlAvailable}
            onChange={(value) => {
                const { aggregationQuery, groupIndex } = hogQLToFilterValue(value)
                if (isFunnelsFilter(filters)) {
                    setFilters({
                        ...filters,
                        aggregation_group_type_index: groupIndex,
                        funnel_aggregate_by_hogql: aggregationQuery,
                    })
                } else {
                    setFilters({
                        ...filters,
                        aggregation_group_type_index: groupIndex,
                    })
                }
            }}
        />
    )
}

const UNIQUE_USERS = 'person_id'
interface AggregationSelectComponentProps {
    className?: string
    hogqlAvailable?: boolean
    value?: string
    onChange: (value: string | undefined) => void
}

function AggregationSelectComponent({
    className,
    hogqlAvailable,
    onChange,
    value,
}: AggregationSelectComponentProps): JSX.Element {
    const { groupTypes, aggregationLabel } = useValues(groupsModel)
    const { needsUpgradeForGroups, canStartUsingGroups } = useValues(groupsAccessLogic)
    const [localValue, setLocalValue] = useState(value)
    useEffect(() => {
        setLocalValue(value)
    }, [value])

    const options: { value: string; label: string }[] = [
        {
            value: UNIQUE_USERS,
            label: 'Unique users',
        },
    ]

    if (!needsUpgradeForGroups && !canStartUsingGroups) {
        groupTypes.forEach((groupType) => {
            options.push({
                value: `$group_${groupType.group_type_index}`,
                label: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
            })
        })
    }

    if (hogqlAvailable) {
        options.push({
            value: `properties.$session_id`,
            label: `Unique sessions`,
        })
    }

    const selectedLabel = options.find((o) => o.value === value)?.label ?? value

    const [open, setOpen] = useState(false)
    const [hogQLOpen, setHogQLOpen] = useState(false)
    const closeBoth = (): void => {
        setOpen(false)
        setHogQLOpen(false)
    }

    return (
        <LemonButtonWithDropdown
            status="stealth"
            type="secondary"
            onClick={() => setOpen(!open)}
            className={className}
            dropdown={{
                actionable: true,
                onClickOutside: closeBoth,
                closeOnClickInside: false,
                visible: open,
                overlay: (
                    <>
                        {options.map((option) => (
                            <LemonButton
                                key={option.value}
                                onClick={() => {
                                    onChange(option.value)
                                    closeBoth()
                                }}
                                status="stealth"
                                fullWidth
                                active={option.value === value}
                            >
                                {option.label}
                            </LemonButton>
                        ))}
                        <LemonButtonWithDropdown
                            status="stealth"
                            onClick={() => setHogQLOpen(!hogQLOpen)}
                            active={selectedLabel === value}
                            fullWidth
                            dropdown={{
                                actionable: true,
                                closeParentPopoverOnClickInside: false,
                                closeOnClickInside: false,
                                visible: hogQLOpen,
                                overlay: (
                                    <div className="w-120" style={{ maxWidth: 'max(60vw, 20rem)' }}>
                                        <LemonTextArea
                                            data-attr="inline-hogql-editor"
                                            value={String(localValue ?? '')}
                                            onChange={(e) => setLocalValue(e)}
                                            onFocus={(e) => {
                                                // move caret to end of input
                                                const val = e.target.value
                                                e.target.value = ''
                                                e.target.value = val
                                            }}
                                            className="font-mono"
                                            minRows={6}
                                            maxRows={6}
                                            autoFocus
                                            placeholder={
                                                'Enter HogQL Expression. Person property access is not enabled.'
                                            }
                                        />
                                        <LemonButton
                                            fullWidth
                                            type="primary"
                                            onClick={() => {
                                                onChange(String(localValue))
                                                closeBoth()
                                            }}
                                            disabled={!localValue}
                                            center
                                        >
                                            Aggregate by HogQL expression
                                        </LemonButton>
                                        <div className="text-right">
                                            <a href="https://posthog.com/manual/hogql" target={'_blank'}>
                                                Learn more about HogQL
                                            </a>
                                        </div>
                                    </div>
                                ),
                            }}
                        >
                            Custom HogQL expression
                        </LemonButtonWithDropdown>
                        {needsUpgradeForGroups || canStartUsingGroups ? (
                            <GroupIntroductionFooter needsUpgrade={needsUpgradeForGroups} />
                        ) : null}
                    </>
                ),
            }}
        >
            {selectedLabel}
        </LemonButtonWithDropdown>
    )
}
