import React from 'react'

import { CurrentPage } from '~/toolbar/stats/CurrentPage'
import { InspectElement } from '~/toolbar/stats/InspectElement'
import { HeatmapStats } from '~/toolbar/stats/HeatmapStats'

export function StatsTab({ className }) {
    return (
        <div className={`toolbar-content ${className}`}>
            <CurrentPage />
            <InspectElement />
            <HeatmapStats />
        </div>
    )
}
