import React from 'react'
import { useActions, useValues } from 'kea'
import { Button } from 'antd'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'

export function EditAction() {
    const { selectedAction } = useValues(actionsTabLogic)
    const { selectAction } = useActions(actionsTabLogic)

    return (
        <div className="toolbar-block">
            <Button onClick={() => selectAction(null)}>Cancel</Button>
            <div>{selectedAction.id}</div>
        </div>
    )
}
