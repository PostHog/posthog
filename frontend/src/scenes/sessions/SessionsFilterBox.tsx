import React from 'react'
import { AimOutlined, SearchOutlined, UsergroupAddOutlined, ContainerOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { SelectBox, SelectedItem } from 'lib/components/SelectBox'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { ActionType, CohortType } from '~/types'
import { EntityTypes } from 'scenes/insights/trendsLogic'
import { ActionInfo } from 'scenes/insights/ActionFilter/ActionFilterDropdown'
import { sessionsFiltersLogic } from 'scenes/sessions/sessionsFiltersLogic'
import { Link } from 'lib/components/Link'
import { cohortsModel } from '~/models/cohortsModel'
import { userLogic } from 'scenes/userLogic'

export function SessionsFilterBox(): JSX.Element {
    const { openFilter } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, closeFilterSelect, dropdownSelected } = useActions(sessionsFiltersLogic)

    const { user } = useValues(userLogic)
    const { actions } = useValues(actionsModel)
    const { cohorts } = useValues(cohortsModel)

    return (
        <>
            <Button
                data-attr="sessions-filter-open"
                onClick={() => (openFilter ? closeFilterSelect() : openFilterSelect('new'))}
            >
                <SearchOutlined />
                <span className="text-muted">Search for users, events, actions...</span>
            </Button>
            {openFilter !== null && (
                <SelectBox
                    selectedItemKey={undefined}
                    onDismiss={closeFilterSelect}
                    onSelect={dropdownSelected}
                    items={[
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
                    ]}
                />
            )}
        </>
    )
}
