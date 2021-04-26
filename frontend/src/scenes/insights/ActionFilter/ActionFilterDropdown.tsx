import React, { RefObject } from 'react'
import { BuiltLogic, useActions, useValues } from 'kea'
import { ActionType, EventDefinition } from '~/types'
import { EntityTypes } from '../../trends/trendsLogic'
import { actionsModel } from '~/models/actionsModel'
import { FireOutlined, InfoCircleOutlined, AimOutlined, ContainerOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'
import { ActionSelectInfo } from '../ActionSelectInfo'
import { SelectBox, SelectedItem } from '../../../lib/components/SelectBox'
import { Link } from 'lib/components/Link'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { eventDefinitionsLogic } from 'scenes/events/eventDefinitionsLogic'

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

const getSuggestions = (events: EventDefinition[]): EventDefinition[] => {
    return events
        .filter((event) => (event.query_usage_30_day || -1) > 0)
        .sort((a, b) => (b.query_usage_30_day || -1) - (a.query_usage_30_day || -1))
        .slice(0, 3)
}

export function ActionFilterDropdown({
    open,
    logic,
    openButtonRef,
    onClose,
}: {
    open: boolean
    logic: BuiltLogic
    openButtonRef?: RefObject<HTMLElement>
    onClose: () => void
}): JSX.Element | null {
    if (!open) {
        return null
    }

    const selectedFilter: FilterType = useValues(logic).selectedFilter
    const { updateFilter, setEntityFilterVisibility } = useActions(logic)

    const { actions } = useValues(actionsModel)
    const { eventDefinitions } = useValues(eventDefinitionsLogic)

    const handleDismiss = (event: MouseEvent): void => {
        if (openButtonRef?.current?.contains(event.target as Node)) {
            return
        }
        onClose()
    }

    const callUpdateFilter = (type: 'actions' | 'events', id: string | number, name: string): void => {
        updateFilter({ type, id, name, index: selectedFilter.index })
        if (selectedFilter.filter.properties?.length) {
            // UX: Open the filter details if this series already has filters to avoid filters being missed
            setEntityFilterVisibility(selectedFilter.index, true)
        }
    }
    const suggestions = getSuggestions(eventDefinitions || [])

    return (
        <SelectBox
            selectedItemKey={selectedFilter ? selectedFilter.filter.type + selectedFilter.filter.id : undefined}
            onDismiss={handleDismiss}
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
                    dataSource: suggestions.map((definition) => ({
                        ...definition,
                        key: 'suggestions' + definition.id,
                    })),
                    renderInfo: function renderSuggestions({ item }) {
                        return (
                            <>
                                <FireOutlined /> Suggestions
                                <br />
                                <h3>{item.name}</h3>
                                {(item?.volume_30_day ?? 0 > 0) && (
                                    <>
                                        Seen <strong>{item.volume_30_day}</strong> times.{' '}
                                    </>
                                )}
                                {(item?.query_usage_30_day ?? 0 > 0) && (
                                    <>
                                        Used in <strong>{item.query_usage_30_day}</strong> queries.
                                    </>
                                )}
                            </>
                        )
                    },
                    type: EntityTypes.EVENTS,
                    getValue: (item: SelectedItem) => item.name || '',
                    getLabel: (item: SelectedItem) => item.name || '',
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
                    renderInfo: ActionInfo,
                    type: EntityTypes.ACTIONS,
                    getValue: (item: SelectedItem) => item.action?.id || '',
                    getLabel: (item: SelectedItem) => item.action?.name || '',
                },
                {
                    name: (
                        <>
                            <ContainerOutlined /> Events
                        </>
                    ),
                    dataSource:
                        eventDefinitions.map((definition) => ({
                            ...definition,
                            key: EntityTypes.EVENTS + definition.id,
                        })) || [],
                    renderInfo: function events({ item }) {
                        return (
                            <>
                                <ContainerOutlined /> Events
                                <br />
                                <h3>{item.name}</h3>
                                {(item?.volume_30_day ?? 0 > 0) && (
                                    <>
                                        Seen <strong>{item.volume_30_day}</strong> times.{' '}
                                    </>
                                )}
                                {(item?.query_usage_30_day ?? 0 > 0) && (
                                    <>
                                        Used in <strong>{item.query_usage_30_day}</strong> queries.
                                    </>
                                )}
                            </>
                        )
                    },
                    type: EntityTypes.EVENTS,
                    getValue: (item: SelectedItem) => item.name || '',
                    getLabel: (item: SelectedItem) => item.name || '',
                },
            ]}
        />
    )
}

export function ActionInfo({ item }: { item: SelectedItem }): JSX.Element {
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
            <h3>
                <PropertyKeyInfo value={item.name} />
            </h3>
            {item.action && <ActionSelectInfo entity={item.action} />}
        </>
    )
}
