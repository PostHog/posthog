import React from 'react'

import { Actions } from '~/toolbar/actions/Actions'
import { useMountedLogic, useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ActionsList } from '~/toolbar/actions/ActionsList'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'

export function ActionsTab({ className }) {
    useMountedLogic(actionsTabLogic)
    const { apiURL, temporaryToken, actionId } = useValues(toolbarLogic)

    return (
        <div className={`toolbar-content ${className}`}>
            <ActionsList />
            <div className="toolbar-block">
                <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
            </div>
        </div>
    )
}
