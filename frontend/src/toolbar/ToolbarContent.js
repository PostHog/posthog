import React from 'react'

import { AllActionsLink } from '~/toolbar/actions/AllActionsLink'
import { AllDashboardsLink } from '~/toolbar/dashboards/AllDashboardsLink'
import { CurrentPage } from '~/toolbar/stats/CurrentPage'
import { InspectElement } from '~/toolbar/shared/InspectElement'
import { PageViewStats } from '~/toolbar/stats/PageViewStats'
import { Actions } from '~/toolbar/actions/Actions'

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
