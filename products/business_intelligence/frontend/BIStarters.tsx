import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { captureBIWorksheetAction } from './biEditorAnalytics'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

export function starterWorksheetUrl(config: BIConfig): string {
    const built = buildBIQuery(config)!
    const worksheet: BIVisualizationNode = { ...built.node, kind: NodeKind.BIVisualizationNode, config }
    return `${urls.businessIntelligenceNew()}?starter=1#q=${encodeURIComponent(JSON.stringify(worksheet))}`
}

const EVENTS_CONFIG: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'events' },
    dateRange: { date_from: '-7d' },
    chartType: ChartDisplayType.ActionsLineGraph,
    rows: [
        {
            id: 'starter:timestamp',
            name: 'timestamp',
            expression: 'timestamp',
            source: { table: 'events' },
            type: 'datetime',
            dateBucket: 'day',
        },
    ],
}

export function BIStarters(): JSX.Element {
    return (
        <section className="flex flex-col gap-2" aria-label="Worksheet starting points">
            <h3 className="m-0">Start with a question</h3>
            <div className="flex flex-wrap gap-2">
                <LemonButton
                    type="secondary"
                    size="small"
                    to={starterWorksheetUrl(EVENTS_CONFIG)}
                    onClick={() =>
                        captureBIWorksheetAction('starter_selected', EVENTS_CONFIG, { starter_kind: 'events' })
                    }
                >
                    Events per day · Last 7 days
                </LemonButton>
            </div>
            <p className="m-0 text-xs text-secondary">
                Choose a starting point, check its definition, then Run. Save your worksheet to return to it or add it
                to a dashboard.
            </p>
        </section>
    )
}
