import React from 'react'
import { AimOutlined, UsergroupAddOutlined, ContainerOutlined, PlaySquareOutlined } from '@ant-design/icons'
import { SelectBox, SelectBoxItem, SelectedItem } from 'lib/components/SelectBox'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, CohortType } from '~/types'
import { EntityTypes } from '~/types'
import { ActionInfo } from 'scenes/insights/ActionFilter/ActionFilterRow/ActionFilterDropdown'
import { FilterSelector, sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'
import { Link } from 'lib/components/Link'
import { cohortsModel } from '~/models/cohortsModel'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { personPropertiesModel } from '~/models/personPropertiesModel'

export function SessionsFilterBox({ selector }: { selector: FilterSelector }): JSX.Element | null {
    const { personProperties } = useValues(personPropertiesModel)
    const { openFilter } = useValues(sessionsFiltersLogic)

    const { closeFilterSelect, dropdownSelected } = useActions(sessionsFiltersLogic)

    const { eventDefinitions } = useValues(eventDefinitionsModel)
    const { actions } = useValues(actionsModel)
    const { cohorts } = useValues(cohortsModel)

    if (openFilter !== selector) {
        return null
    }

    const groups: Array<SelectBoxItem> = [
        {
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
            key: 'action_type',
            getValue: (item: SelectedItem) => item.action?.id || '',
            getLabel: (item: SelectedItem) => item.action?.name || '',
        },
        {
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
            key: 'event_type',
            getValue: (item: SelectedItem) => item.name,
            getLabel: (item: SelectedItem) => item.name,
        },
        {
            name: 'Cohorts',
            header: function cohortHeader(label) {
                return (
                    <>
                        <UsergroupAddOutlined /> {label}
                    </>
                )
            },
            dataSource: cohorts.map((cohort: CohortType) => ({
                key: 'cohorts' + cohort.id,
                name: cohort.name || '',
                id: cohort.id,
                cohort,
            })),
            renderInfo: function renderCohorts({ item }) {
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
                                <strong>{item.cohort.count}</strong> persons in cohort.
                            </>
                        )}
                    </>
                )
            },
            type: 'cohort',
            key: 'cohort',
            getValue: (item: SelectedItem) => item.id || '',
            getLabel: (item: SelectedItem) => item.name,
        },
    ]

    if (personProperties.length > 0) {
        groups.unshift({
            name: 'User properties',
            header: function userHeader(label) {
                return (
                    <>
                        <UsergroupAddOutlined /> {label}
                    </>
                )
            },
            dataSource: personProperties.map(({ name, count }) => ({
                key: 'person' + name,
                name: name,
                usage_count: count,
            })),
            renderInfo: function renderPersonProperty({ item }) {
                return (
                    <>
                        <UsergroupAddOutlined /> Person property
                        <br />
                        <h3>{item.name}</h3>
                        {item?.query_usage_30_day && (
                            <>
                                <strong>{item.query_usage_30_day}</strong> persons have this property.
                            </>
                        )}
                    </>
                )
            },
            key: 'person',
            type: 'person',
            getValue: (item: SelectedItem) => item.name,
            getLabel: (item: SelectedItem) => item.name,
        })
    }

    groups.unshift({
        name: 'Recording properties',
        header: function userPropertiesHeader(label) {
            return (
                <>
                    <PlaySquareOutlined /> {label}
                </>
            )
        },
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
        key: 'recording',
        type: 'recording',
        getValue: (item: SelectedItem) => item.value || '',
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
