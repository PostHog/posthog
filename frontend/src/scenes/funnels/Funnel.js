import React from 'react'
import { Card, Loading } from '../../lib/utils'
import { SaveToDashboard } from '../../lib/components/SaveToDashboard'
import { DateFilter } from '../../lib/components/DateFilter'
import { EditFunnel } from './EditFunnel'
import { FunnelViz } from './FunnelViz'
import { People } from './People'
import { funnelLogic } from './funnelLogic'
import { useValues, useActions } from 'kea'

export function Funnel({ match }) {
    const { funnel, funnelLoading, stepsWithCount, stepsWithCountLoading, filters } = useValues(
        funnelLogic({ id: match.params.id })
    )
    const { setFilters } = useActions(funnelLogic({ id: match.params.id }))
    if (funnelLoading || !funnel) return <Loading />
    return (
        <div className="funnel">
            <h1>Funnel: {funnel.name}</h1>
            <EditFunnel funnelId={match.params.id} />
            <Card
                title={
                    <span>
                        <span className="float-right">
                            <DateFilter
                                onChange={(date_from, date_to) =>
                                    setFilters({
                                        date_from,
                                        date_to,
                                    })
                                }
                                dateFrom={filters.date_from}
                                dateTo={filters.date_to}
                            />
                            <SaveToDashboard filters={{ funnel_id: funnel.id }} type="FunnelViz" name={funnel.name} />
                        </span>
                        Graph
                    </span>
                }
            >
                <div style={{ height: 300 }}>
                    {stepsWithCountLoading && <Loading />}
                    {stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1 && (
                        <FunnelViz funnel={{ steps: stepsWithCount }} />
                    )}
                </div>
            </Card>
            <People match={match} />
        </div>
    )
}
