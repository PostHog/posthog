import React from 'react'

import { CurrentPage } from '~/toolbar/stats/CurrentPage'
import { InspectElement } from '~/toolbar/shared/InspectElement'
import { PageViewStats } from '~/toolbar/stats/PageViewStats'

export function StatsTab({ className }) {
    return (
        <div className={`toolbar-content ${className}`}>
            <CurrentPage />
            <InspectElement />
            <PageViewStats />
        </div>
    )
}
