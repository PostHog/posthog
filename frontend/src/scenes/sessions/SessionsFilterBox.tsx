import React, { useState } from 'react'
import { AimOutlined, DownOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { SelectBox } from 'lib/components/SelectBox'
import { useValues } from 'kea'
import { actionsModel } from '~/models/actionsModel'
import { ActionType } from '~/types'
import { EntityTypes } from 'scenes/insights/trendsLogic'
import { ActionInfo } from 'scenes/insights/ActionFilter/ActionFilterDropdown'

interface Props {
    i?: boolean
}

export function SessionsFilterBox({}: Props): JSX.Element {
    const [open, setOpen] = useState<boolean>(false)

    const { actions } = useValues(actionsModel)

    return (
        <div>
            <Button data-attr="sessions-filter-open" onClick={(): void => setOpen(!open)}>
                {false || 'Add filter'}
                <DownOutlined className="text-muted" style={{ marginRight: '-6px' }} />
            </Button>
            {open && (
                <SelectBox
                    selectedItemKey={undefined}
                    onDismiss={() => setOpen(false)}
                    onSelect={() => {}}
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
        </div>
    )
}
