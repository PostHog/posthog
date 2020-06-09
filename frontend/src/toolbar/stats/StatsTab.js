import React from 'react'

import { CurrentPage } from '~/toolbar/stats/CurrentPage'
import { InspectElement } from '~/toolbar/shared/InspectElement'
import { PageViewStats } from '~/toolbar/stats/PageViewStats'
import { HeatmapStats } from '~/toolbar/shared/HeatmapStats'

export function StatsTab({ className }) {
    return (
        <div className={`toolbar-content ${className}`}>
            <CurrentPage />
            <HeatmapStats />
            <InspectElement />
            <PageViewStats />
        </div>
    )
}
