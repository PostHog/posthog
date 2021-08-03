import React from 'react'
import { AimOutlined, ContainerOutlined } from '@ant-design/icons'
import { SelectBox, SelectBoxItem, SelectedItem } from 'lib/components/SelectBox'
import { useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { ActionType } from '~/types'
import { EntityTypes } from '~/types'
import { ActionInfo } from 'scenes/insights/ActionFilter/ActionFilterRow/ActionFilterDropdown'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'

export function CohortEntityFilterBox({
    open = false,
    onSelect,
}: {
    open: boolean
    onSelect: (type: any, id: string | number, name: string) => void
}): JSX.Element | null {
    const { eventDefinitions } = useValues(eventDefinitionsModel)
    const { actions } = useValues(actionsModel)

    if (!open) {
        return null
    }

    const groups: Array<SelectBoxItem> = [
        {
            key: 'actions',
            name: 'Actions',
            header: function actionHeader(label) {
                return (
                    <>
                        <AimOutlined /> {label}
                    </>
                )
            },
            dataSource: actions.map((action: ActionType) => ({
                key: EntityTypes.ACTIONS + action.id,
                name: action.name,
                volume: action.count,
                id: action.id,
                action,
            })),
            renderInfo: ActionInfo,
            type: 'action_type',
            getValue: (item: SelectedItem) => item.action?.id || '',
            getLabel: (item: SelectedItem) => item.action?.name || '',
        },
        {
            key: 'events',
            name: 'Events',
            header: function eventHeader(label) {
                return (
                    <>
                        <ContainerOutlined /> {label}
                    </>
                )
            },
            dataSource:
                eventDefinitions.map((definition) => ({
                    key: EntityTypes.EVENTS + definition.name,
                    ...definition,
                })) || [],
            renderInfo: function events({ item }) {
                return (
                    <>
                        <ContainerOutlined /> Events
                        <br />
                        <h3>{item.name}</h3>
                        {item?.volume_30_day && (
                            <>
                                Seen <strong>{item.volume_30_day}</strong> times.{' '}
                            </>
                        )}
                        {item?.query_usage_30_day && (
                            <>
                                Used in <strong>{item.query_usage_30_day}</strong> queries.
                            </>
                        )}
                    </>
                )
            },
            type: 'event_type',
            getValue: (item: SelectedItem) => item.name,
            getLabel: (item: SelectedItem) => item.name,
        },
    ]

    return <SelectBox selectedItemKey={undefined} onDismiss={() => {}} onSelect={onSelect} items={groups} />
}
