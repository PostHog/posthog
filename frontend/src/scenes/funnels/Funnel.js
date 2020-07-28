import React from 'react'
import { Card, Loading } from 'lib/utils'
import { SaveToDashboard } from 'lib/components/SaveToDashboard/SaveToDashboard'
import { DateFilter } from 'lib/components/DateFilter'
import { EditFunnel } from './EditFunnel'
import { FunnelViz } from './FunnelViz'
import { People } from './People'
import { funnelLogic } from './funnelLogic'
import { useValues, useActions } from 'kea'
import { hot } from 'react-hot-loader/root'

export const Funnel = hot(_Funnel)
function _Funnel({ id }) {
    const { funnel, funnelLoading, stepsWithCount, stepsWithCountLoading } = useValues(funnelLogic({ id }))
    const { setFunnel } = useActions(funnelLogic({ id }))
    if (!funnel && funnelLoading) return <Loading />
    return (
        <div className="funnel">
            {funnel.id ? <h1>Funnel: {funnel.name}</h1> : <h1>New funnel</h1>}
            <p style={{ maxWidth: 600 }}>
                <i>Add multiple actions and event (order sensitive) and save to see the funnel visualization</i>
            </p>
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
                                <SaveToDashboard funnelId={funnel.id} type="FunnelViz" name={funnel.name} />
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
            {funnel.id && <People id={id} />}
        </div>
    )
}
