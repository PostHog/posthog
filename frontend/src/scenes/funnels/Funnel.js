import React from 'react'
import { Card, Loading } from '../../lib/utils'
import { SaveToDashboard } from '../../lib/components/SaveToDashboard'
import { DateFilter } from '../../lib/components/DateFilter'
import { EditFunnel } from './EditFunnel'
import { FunnelViz } from './FunnelViz'
import { People } from './People'
import { funnelLogic } from './funnelLogic'
import { useValues, useActions } from 'kea'
import api from 'lib/api'

export function Funnel({ match }) {
    const id = match.params.id
    const { funnel, funnelLoading, stepsWithCount, stepsWithCountLoading } = useValues(funnelLogic({ id }))
    const { setFunnel } = useActions(funnelLogic({ id }))
    if (!funnel && funnelLoading) return <Loading />
    return (
        <div className="funnel">
            {funnel.id ? <h1>Funnel: {funnel.name}</h1> : <h1>New funnel</h1>}
            <EditFunnel funnelId={id} />

            {funnel.id && (
                <Card
                    title={
                        <span>
                            <span className="float-right">
                                <DateFilter
                                    onChange={(date_from, date_to) =>
                                        setFunnel(
                                            {
                                                filters: {
                                                    date_from,
                                                    date_to,
                                                },
                                            },
                                            true
                                        )
                                    }
                                    dateFrom={funnel.filters.date_from}
                                    dateTo={funnel.filters.date_to}
                                />
                                <SaveToDashboard
                                    name={funnel.name}
                                    onSubmit={(value, callback) => {
                                        api.create('api/dashboard', {
                                            filters: { funnel_id: funnel.id },
                                            type: 'FunnelViz',
                                            name: value,
                                        }).then(callback)
                                    }}
                                />
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
            )}
            {funnel.id && <People match={match} />}
        </div>
    )
}
