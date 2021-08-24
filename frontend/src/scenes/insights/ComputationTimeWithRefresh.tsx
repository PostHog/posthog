import { Button } from 'antd'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import React, { useEffect, useState } from 'react'
import { Tooltip } from 'antd'

dayjs.extend(relativeTime)

export interface ComputationTimeWithRefreshProps {
    lastRefresh: string
    loadResults: (refresh: boolean) => void
}

export function ComputationTimeWithRefresh({ lastRefresh, loadResults }: ComputationTimeWithRefreshProps): JSX.Element {
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
        <div className="text-muted-alt" style={{ marginLeft: 'auto' }}>
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
                    disabled={dayjs().subtract(3, 'minutes') <= dayjs(lastRefresh)}
                    style={{ padding: 0 }}
                >
                    <span style={{ fontSize: 14 }}>Refresh</span>
                </Button>
            </Tooltip>
        </div>
    )
}
