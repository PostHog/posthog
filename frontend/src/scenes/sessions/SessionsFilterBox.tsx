import React from 'react'
import { AimOutlined, SearchOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { SelectBox } from 'lib/components/SelectBox'
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
    const { closeFilterSelect } = useActions(sessionsFiltersLogic)
    const { actions } = useValues(actionsModel)

    return (
        <>
            <Button data-attr="sessions-filter-open" onClick={() => !open ? closeFilterSelect() : null}>
                <SearchOutlined />
                <span className="text-muted">Search  for users, events, actions...</span>
                {/* <DownOutlined className="text-muted" style={{ marginRight: '-6px' }} /> */}
            </Button>
            {openFilter && (
                <SelectBox
                    selectedItemKey={undefined}
                    onDismiss={closeFilterSelect}
                    onSelect={(...args) => console.log(args)}
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
                        },
                    ]}
                />
            )}
        </>
    )
}
