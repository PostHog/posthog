import React from 'react'

import { AllActionsLink } from '~/toolbar/actions/AllActionsLink'
import { InspectElement } from '~/toolbar/shared/InspectElement'
import { PageViewStats } from '~/toolbar/stats/PageViewStats'
import { Actions } from '~/toolbar/actions/Actions'
import { useValues } from 'kea'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

export function ActionsTab({ className, type }) {
    const { apiURL, temporaryToken, actionId } = useValues(toolbarLogic)

    return (
        <div className={`toolbar-content ${className}`}>
            <AllActionsLink type={type} />
            <InspectElement />
            <PageViewStats />
            <div className="toolbar-block">
                <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
            </div>
        </div>
    )
}
