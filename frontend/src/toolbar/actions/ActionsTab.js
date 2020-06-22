import React from 'react'

import { Actions } from '~/toolbar/actions/Actions'
import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { ActionsList } from '~/toolbar/actions/ActionsList'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { EditAction } from '~/toolbar/actions/EditAction'

export function ActionsTab({ className }) {
    const { selectedAction } = useValues(actionsTabLogic)
    const { apiURL, temporaryToken, actionId } = useValues(toolbarLogic)

    return (
        <div className={`toolbar-content ${className}`}>
            {selectedAction ? (
                <EditAction />
            ) : (
                <>
                    <ActionsList />
                    <div className="toolbar-block">
                        <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
                    </div>
                </>
            )}
        </div>
    )
}
