import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { InsightTooltip } from './InsightTooltip'
import { Insight } from '../Insight'

export default {
    title: 'Components/InsightTooltip',
    component: InsightTooltip,
} as ComponentMeta<typeof Insight>

export function FunnelTrendsTooltip(): JSX.Element {
    return (
        <div style={{ height: 300 }}>
            <div style={{ maxWidth: '30rem' }} className="ph-graph-tooltip center top">
                <InsightTooltip
                    date="2022-06-06"
                    timezone="UTC"
                    seriesData={[
                        {
                            id: 0,
                            dataIndex: 30,
                            datasetIndex: 1,
                            dotted: true,
                            color: '#1d4aff',
                            count: 71.4,
                            filter: {},
                            reached_from_step_count: 7,
                            reached_to_step_count: 5,
                        },
                    ]}
                    hideColorCol={true}
                    forceEntitiesAsColumns={false}
                    hideInspectActorsSection={false}
                    groupTypeLabel="people"
                    showHeader={true}
                    renderSeries={() => {
                        return (
                            <div style={{ paddingTop: 20 }}>
                                Percentage
                                <br />
                                Entered/completed
                            </div>
                        )
                    }}
                    renderCount={(count, datum) => {
                        if (!datum.reached_from_step_count || !datum.reached_to_step_count) {
                            return null
                        }
                        return (
                            <>
                                {count}%<br />
                                {datum.reached_from_step_count}/{datum.reached_to_step_count}{' '}
                            </>
                        )
                    }}
                />
            </div>
        </div>
    )
}
