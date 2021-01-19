import React from 'react'
import { AimOutlined, UsergroupAddOutlined, ContainerOutlined, PlaySquareOutlined } from '@ant-design/icons'
import { SelectBox, SelectBoxItem, SelectedItem } from 'lib/components/SelectBox'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, CohortType } from '~/types'
import { EntityTypes } from 'scenes/insights/trendsLogic'
import { ActionInfo } from 'scenes/insights/ActionFilter/ActionFilterDropdown'
import { FilterSelector, sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { Link } from 'lib/components/Link'
import { cohortsModel } from '~/models/cohortsModel'
import { userLogic } from 'scenes/userLogic'

export function SessionsFilterBox({ selector }: { selector: FilterSelector }): JSX.Element | null {
    const { openFilter, personProperties } = useValues(sessionsFiltersLogic)

    const { closeFilterSelect, dropdownSelected } = useActions(sessionsFiltersLogic)

    const { user } = useValues(userLogic)
    const { actions } = useValues(actionsModel)
    const { cohorts } = useValues(cohortsModel)

    if (openFilter !== selector) {
        return null
    }

    const groups: Array<SelectBoxItem> = [
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
            type: 'action_type',
            getValue: (item: SelectedItem) => item.action?.id,
            getLabel: (item: SelectedItem) => item.action?.name,
        },
        {
            name: (
                <>
                    <ContainerOutlined /> Events
                </>
            ),
            dataSource:
                user?.team?.event_names_with_usage.map((event) => ({
                    key: EntityTypes.EVENTS + event.event,
                    name: event.event,
                    ...event,
                })) || [],
            renderInfo: function events({ item }) {
                return (
                    <>
                        <ContainerOutlined /> Events
                        <br />
                        <h3>{item.name}</h3>
                        {item?.volume && (
                            <>
                                Seen <strong>{item.volume}</strong> times.{' '}
                            </>
                        )}
                        {item?.usage_count && (
                            <>
                                Used in <strong>{item.usage_count}</strong> queries.
                            </>
                        )}
                    </>
                )
            },
            type: 'event_type',
            getValue: (item: SelectedItem) => item.event,
            getLabel: (item: SelectedItem) => item.event,
        },
        {
            name: (
                <>
                    <UsergroupAddOutlined /> Cohorts
                </>
            ),
            dataSource: cohorts.map((cohort: CohortType) => ({
                key: 'cohorts' + cohort.id,
                name: cohort.name,
                id: cohort.id,
                cohort,
            })),
            renderInfo: function cohorts({ item }) {
                return (
                    <>
                        <UsergroupAddOutlined /> Cohorts
                        <Link
                            to={`/cohorts/${item.id}#backTo=Insights&backToURL=${encodeURIComponent(
                                window.location.pathname + window.location.search
                            )}`}
                            style={{ float: 'right' }}
                        >
                            edit
                        </Link>
                        <br />
                        <h3>{item.name}</h3>
                        {item?.cohort?.count && (
                            <>
                                <strong>{item.cohort.count}</strong> users in cohort.
                            </>
                        )}
                    </>
                )
            },
            type: 'cohort',
            getValue: (item: SelectedItem) => item.id,
            getLabel: (item: SelectedItem) => item.name,
        },
    ]

    if (personProperties.length > 0) {
        groups.unshift({
            name: (
                <>
                    <UsergroupAddOutlined /> User properties
                </>
            ),
            dataSource: personProperties.map(({ name, count }) => ({
                key: 'person' + name,
                name: name,
                usage_count: count,
            })),
            renderInfo: function userProperty({ item }) {
                return (
                    <>
                        <UsergroupAddOutlined /> User property
                        <br />
                        <h3>{item.name}</h3>
                        {item?.usage_count && (
                            <>
                                <strong>{item.usage_count}</strong> users have this property.
                            </>
                        )}
                    </>
                )
            },
            type: 'person',
            getValue: (item: SelectedItem) => item.name,
            getLabel: (item: SelectedItem) => item.name,
        })
    }

    groups.unshift({
        name: (
            <>
                <PlaySquareOutlined /> Recording properties
            </>
        ),
        dataSource: [
            { key: 'duration', name: 'Recording duration', value: 'duration' },
            { key: 'unseen', name: 'Unseen recordings', value: 'unseen' },
        ],
        renderInfo: function recordingProperty({ item }) {
            return (
                <>
                    <PlaySquareOutlined /> Recording properties
                    <br />
                    <h3>{item.name}</h3>
                </>
            )
        },
        type: 'recording',
        getValue: (item: SelectedItem) => item.value,
        getLabel: (item: SelectedItem) => item.name,
    })

    return (
        <SelectBox
            selectedItemKey={undefined}
            onDismiss={closeFilterSelect}
            onSelect={dropdownSelected}
            items={groups}
        />
    )
}
