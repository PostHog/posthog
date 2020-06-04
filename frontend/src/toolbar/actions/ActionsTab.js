import React from 'react'

import { AllActionsLink } from '~/toolbar/actions/AllActionsLink'
import { InspectElement } from '~/toolbar/shared/InspectElement'
import { PageViewStats } from '~/toolbar/stats/PageViewStats'
import { Actions } from '~/toolbar/actions/Actions'

export function ActionsTab({ apiURL, temporaryToken, actionId, className, type }) {
    return (
        <div className={`toolbar-content ${className}`}>
            <AllActionsLink apiURL={apiURL} type={type} />
            <InspectElement />
            <PageViewStats />
            <div className="toolbar-block">
                <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
            </div>
        </div>
    )
}
