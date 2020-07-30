import React from 'react'

import { CurrentPage } from '~/toolbar/stats/CurrentPage'
import { InspectElement } from '~/toolbar/stats/InspectElement'
import { HeatmapStats } from '~/toolbar/stats/HeatmapStats'

export function StatsTab(): JSX.Element {
    return (
        <div className={`toolbar-content toolbar-block`}>
            <CurrentPage />
            <br />
            <InspectElement />
            <br />
            <HeatmapStats />
        </div>
    )
}
