import React from 'react'
import { useActions, useValues } from 'kea'
import { ActionType } from '~/types'
import { EventUsageType } from '~/types'
import { EntityTypes } from '../trendsLogic'
import { userLogic } from 'scenes/userLogic'
import { actionsModel } from '~/models/actionsModel'
import { FireOutlined, InfoCircleOutlined, AimOutlined, ContainerOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { ActionSelectInfo } from '../ActionSelectInfo'
import { entityFilterLogicType } from 'types/scenes/insights/ActionFilter/entityFilterLogicType'
import { SelectBox } from '../../../lib/components/SelectBox'

const getSuggestions = (events: EventUsageType[]): EventUsageType[] => {
    return events
        .filter((event) => event.usage_count > 0)
        .sort((a, b) => b.usage_count - a.usage_count)
        .slice(0, 3)
}
export function ActionFilterDropdown({
    onClickOutside,
    logic,
}: {
    onClickOutside: CallableFunction
    logic: entityFilterLogicType
}): JSX.Element {
    const { selectedFilter } = useValues(logic)
    const { updateFilter } = useActions(logic)
    const { actions } = useValues(actionsModel)
    const { user } = useValues(userLogic)

    const callUpdateFilter = (type: string, value: string, name: string): CallableFunction =>
        updateFilter({ type, value, name, index: selectedFilter.index })
    const suggestions = getSuggestions(user?.team.event_names_with_usage)

    return (
        <SelectBox
            selectedItemKey={selectedFilter.filter?.type + selectedFilter.filter?.id}
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
                        action,
                    })),
                    renderInfo: function actions({ item }) {
                        return (
                            <>
                                <AimOutlined /> Actions
                                <br />
                                <h3>{item.name}</h3>
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
