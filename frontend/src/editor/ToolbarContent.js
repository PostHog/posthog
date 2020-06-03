import React from 'react'

import { AllActionsLink } from '~/editor/AllActionsLink'
import { AllDashboardsLink } from '~/editor/AllDashboardsLink'
import { CurrentPage } from '~/editor/CurrentPage'
import { InspectElement } from '~/editor/InspectElement'
import { PageViewStats } from '~/editor/PageViewStats'
import { Actions } from '~/editor/Actions'

export function ToolbarContent({ tab, apiURL, temporaryToken, actionId, className, type }) {
    return (
        <div className={`toolbar-content ${className}`}>
            {tab === 'actions' ? <AllActionsLink apiURL={apiURL} type={type} /> : null}
            {tab === 'dashboards' ? <AllDashboardsLink apiURL={apiURL} type={type} /> : null}
            {tab === 'stats' ? <CurrentPage /> : null}
            {tab === 'actions' || tab === 'stats' ? <InspectElement /> : null}
            {tab === 'actions' || tab === 'stats' ? <PageViewStats /> : null}
            {tab === 'actions' ? (
                <div className="toolbar-block">
                    <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
                </div>
            ) : null}
        </div>
    )
}
