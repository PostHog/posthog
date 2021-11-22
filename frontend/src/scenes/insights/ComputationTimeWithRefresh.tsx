import { Button } from 'antd'
import React, { useEffect, useState } from 'react'
import { Tooltip } from 'antd'
import { useActions, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { dayjs } from 'lib/dayjs'

export function ComputationTimeWithRefresh(): JSX.Element {
    const { lastRefresh } = useValues(insightLogic)
    const { loadResults } = useActions(insightLogic)
    const [, setRerenderCounter] = useState(0)

    useEffect(() => {
        const rerenderInterval = setInterval(() => {
            setRerenderCounter((previousValue) => previousValue + 1)
        }, 30000)
        return () => {
            clearInterval(rerenderInterval)
        }
    }, [])

    return (
        <div
            className="text-muted-alt"
            style={{ marginLeft: 'auto', height: 32, display: 'flex', alignItems: 'center' }}
        >
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            <span style={{ padding: '0 4px' }}>•</span>
            <Tooltip
                title={
                    <>
                        Insights can be refreshed
                        <br />
                        every 3 minutes.
                    </>
                }
            >
                <Button
                    size="small"
                    type="link"
                    onClick={() => loadResults(true)}
                    disabled={!!lastRefresh && dayjs().subtract(3, 'minutes') <= dayjs(lastRefresh)}
                    style={{ padding: 0 }}
                >
                    <span style={{ fontSize: 14 }}>Refresh</span>
                </Button>
            </Tooltip>
        </div>
    )
}
