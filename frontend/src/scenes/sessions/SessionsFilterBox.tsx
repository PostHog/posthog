import React from 'react'
import { AimOutlined, SearchOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { SelectBox, SelectedItem } from 'lib/components/SelectBox'
import { useActions, useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { ActionType } from '~/types'
import { EntityTypes } from 'scenes/insights/trendsLogic'
import { ActionInfo } from 'scenes/insights/ActionFilter/ActionFilterDropdown'
import { sessionsFiltersLogic } from 'scenes/sessions/sessionsFiltersLogic'

interface Props {
    i?: boolean
}

export function SessionsFilterBox({}: Props): JSX.Element {
    const { openFilter } = useValues(sessionsFiltersLogic)
    const { openFilterSelect, closeFilterSelect, dropdownSelected } = useActions(sessionsFiltersLogic)
    const { actions } = useValues(actionsModel)

    return (
        <>
            <Button data-attr="sessions-filter-open" onClick={() => openFilter ? closeFilterSelect() : openFilterSelect('new')}>
                <SearchOutlined />
                <span className="text-muted">Search  for users, events, actions...</span>
                {/* <DownOutlined className="text-muted" style={{ marginRight: '-6px' }} /> */}
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
                            type: "action_type",
                            getValue: (item: SelectedItem) => item.action?.id,
                            getLabel: (item: SelectedItem) => item.action?.name,
                        },
                    ]}
                />
            )}
        </>
    )
}
