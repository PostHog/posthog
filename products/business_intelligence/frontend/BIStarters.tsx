import { useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { captureBIWorksheetAction } from './biEditorAnalytics'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'
import { biStartersLogic } from './biStartersLogic'

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
    const { metrics, sources } = useValues(biStartersLogic)
    return (
        <section className="flex flex-col gap-2" aria-label="Worksheet starting points">
            <h3 className="m-0">Start with a question</h3>
            <div className="flex flex-wrap gap-2">
                {metrics.map((metric) => (
                    <LemonButton
                        key={metric.id}
                        type="secondary"
                        size="small"
                        className="max-w-full"
                        to={`${urls.businessIntelligenceNew()}?metric=${encodeURIComponent(metric.name)}`}
                        tooltip={`${metric.description} · Fixed query snapshot; dates and dimensions are not editable.`}
                        onClick={() =>
                            captureBIWorksheetAction('starter_selected', DEFAULT_BI_CONFIG, { starter_kind: 'metric' })
                        }
                    >
                        <span className="flex items-center gap-1 min-w-0">
                            <span className="truncate">Explore {metric.display_name || metric.name}</span>
                            <LemonTag type="success">Approved metric</LemonTag>
                        </span>
                    </LemonButton>
                ))}
                {sources.map((source) => {
                    const config = { ...DEFAULT_BI_CONFIG, source: { table: source.target_name } }
                    return (
                        <LemonButton
                            key={source.id}
                            type="secondary"
                            size="small"
                            className="max-w-full"
                            to={starterWorksheetUrl(config)}
                            tooltip={source.notes}
                            onClick={() =>
                                captureBIWorksheetAction('starter_selected', config, {
                                    starter_kind: 'certified_source',
                                })
                            }
                        >
                            <span className="flex items-center gap-1 min-w-0">
                                <span className="truncate">Explore {source.target_name}</span>
                                <LemonTag type="success">Certified</LemonTag>
                            </span>
                        </LemonButton>
                    )
                })}
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
