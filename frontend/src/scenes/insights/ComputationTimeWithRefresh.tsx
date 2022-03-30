import { Button } from 'antd'
import React from 'react'
import { Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { InsightType } from '~/types'

const REFRESH_INTERVAL_MINUTES = 3

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { lastRefresh, activeView, insight } = useValues(insightLogic)
    const { loadResults, setActiveView, setFilters } = useActions(insightLogic)

    usePeriodicRerender(15000)

    const onClickSource = (): void => {
        setFilters({
            insight: InsightType.USER_SQL,
            user_sql: insight.source_query,
        })
        setActiveView(InsightType.USER_SQL)
    }

    return (
        <div className="text-muted-alt" style={{ height: 32, display: 'flex', alignItems: 'center' }}>
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            <span style={{ padding: '0 4px' }}>•</span>
            <Tooltip
                title={
                    <>
                        Insights can be refreshed
                        <br />
                        every {REFRESH_INTERVAL_MINUTES} minutes.
                    </>
                }
            >
                <Button
                    size="small"
                    type="link"
                    onClick={() => loadResults(true)}
                    disabled={
                        !!lastRefresh &&
                        dayjs()
                            .subtract(REFRESH_INTERVAL_MINUTES - 0.5, 'minutes')
                            .isBefore(lastRefresh)
                    }
                    style={{ padding: 0 }}
                >
                    <span style={{ fontSize: 14 }}>Refresh</span>
                </Button>
            </Tooltip>
            {activeView !== InsightType.TRENDS && (
                <>
                    <span style={{ padding: '0 4px' }}>•</span>
                    <Button size="small" type="link" onClick={onClickSource} style={{ padding: 0 }}>
                        <span style={{ fontSize: 14 }}>View source SQL</span>
                    </Button>
                </>
            )}
        </div>
    )
}
