import { Button } from 'antd'
import React from 'react'
import { Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'

const REFRESH_INTERVAL_MINUTES = 3

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { lastRefresh } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)

    usePeriodicRerender(15000)

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
        </div>
    )
}
