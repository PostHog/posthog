import React from 'react'
import { useValues } from 'kea'
import { ActionType } from '~/types'
import { EventUsageType } from '~/types'
import { EntityTypes } from '../trendsLogic'
import { userLogic } from 'scenes/userLogic'
import { actionsModel } from '~/models/actionsModel'
import { FireOutlined, InfoCircleOutlined, AimOutlined, ContainerOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { ActionSelectInfo } from '../ActionSelectInfo'
import { SelectBox } from '../../../lib/components/SelectBox'
import { Link } from 'lib/components/Link'

interface FilterType {
    filter: {
        id: string
        type: 'actions' | 'events'
        name: string
        order: number
        math?: string
        math_property?: string
        properties?: Array<Record<string, any>>
    }
    type: 'actions' | 'events'
    index: number
}

const getSuggestions = (events: EventUsageType[]): EventUsageType[] => {
    return events
        .filter((event) => event.usage_count > 0)
        .sort((a, b) => b.usage_count - a.usage_count)
        .slice(0, 3)
}
export function ActionFilterDropdown({
    open,
    selectedFilter,
    updateFilter,
    onClickOutside,
}: {
    open: boolean
    selectedFilter?: FilterType
    updateFilter: (value: { type: 'actions' | 'events'; value: string | number; name: string; index: number }) => void
    onClickOutside: (event: MouseEvent) => void
}): JSX.Element | null {
    if (!open || !selectedFilter) {
        return null
    }

    const { actions } = useValues(actionsModel)
    const { user } = useValues(userLogic)

    const callUpdateFilter = (type: 'actions' | 'events', value: string, name: string): void => {
        updateFilter({ type, value, name, index: selectedFilter.index })
    }
    const suggestions = getSuggestions(user?.team?.event_names_with_usage || [])

    return (
        <SelectBox
            selectedItemKey={selectedFilter ? selectedFilter.filter.type + selectedFilter.filter.id : undefined}
            onDismiss={onClickOutside}
            onSelect={callUpdateFilter}
            items={[
                {
                    name: (
                        <>
                            <FireOutlined /> Suggested for you{' '}
                            <Tooltip title="We'll suggest events you (or your team) have used frequently in other queries">
                                <InfoCircleOutlined />
                            </Tooltip>
                        </>
                    ),
                    dataSource: suggestions.map((event) => ({
                        key: 'suggestions' + event.event,
                        name: event.event,
                        ...event,
                    })),
                    renderInfo: function suggestions({ item }) {
                        return (
                            <>
                                <FireOutlined /> Suggestions
                                <br />
                                <h3>{item.name}</h3>
                                {item?.volume > 0 && (
                                    <>
                                        Seen <strong>{item.volume}</strong> times.{' '}
                                    </>
                                )}
                                {item?.usage_count > 0 && (
                                    <>
                                        Used in <strong>{item.usage_count}</strong> queries.
                                    </>
                                )}
                            </>
                        )
                    },
                },
                {
                    name: (
                        <>
                            <AimOutlined /> Actions
                        </>
                    ),
                    dataSource: actions.map((action: ActionType) => ({
                        key: EntityTypes.ACTIONS + action.id,
                        name: action.name,
                        volume: action.count,
                        id: action.id,
                        action,
                    })),
                    renderInfo: function actions({ item }) {
                        return (
                            <>
                                <AimOutlined /> Actions
                                <Link
                                    to={`/action/${item.id}#backTo=Insights&backToURL=${encodeURIComponent(
                                        window.location.pathname + window.location.search
                                    )}`}
                                    style={{ float: 'right' }}
                                >
                                    edit
                                </Link>
                                <br />
                                <h3>{item.name} </h3>
                                {item.action && <ActionSelectInfo entity={item.action} />}
                            </>
                        )
                    },
                },
                {
                    name: (
                        <>
                            <ContainerOutlined /> Events
                        </>
                    ),
                    dataSource: user?.team.event_names_with_usage.map((event) => ({
                        key: EntityTypes.EVENTS + event.event,
                        name: event.event,
                        ...event,
                    })),
                    renderInfo: function events({ item }) {
                        return (
                            <>
                                <ContainerOutlined /> Events
                                <br />
                                <h3>{item.name}</h3>
                                {item?.volume > 0 && (
                                    <>
                                        Seen <strong>{item.volume}</strong> times.{' '}
                                    </>
                                )}
                                {item?.usage_count > 0 && (
                                    <>
                                        Used in <strong>{item.usage_count}</strong> queries.
                                    </>
                                )}
                            </>
                        )
                    },
                },
            ]}
        />
    )
}
