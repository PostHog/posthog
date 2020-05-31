import React from 'react'
import { Actions } from '~/editor/Actions'
import { CurrentPage } from '~/editor/CurrentPage'
import { PageViewStats } from '~/editor/PageViewStats'
import { InspectElement } from '~/editor/InspectElement'

export function Toolbar({ apiURL, temporaryToken, actionId }) {
    return (
        <div>
            <CurrentPage />
            <InspectElement />
            <PageViewStats />
            <div className="float-box">
                <Actions apiURL={apiURL} temporaryToken={temporaryToken} actionId={actionId} />
            </div>
        </div>
    )
}
