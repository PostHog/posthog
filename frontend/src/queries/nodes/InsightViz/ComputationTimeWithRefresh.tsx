import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { Button } from 'antd'

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { lastRefresh, insightRefreshButtonDisabledReason, isTestGroupForNewRefreshUX } = useValues(dataNodeLogic)
    const { loadData } = useActions(dataNodeLogic)

    usePeriodicRerender(15000)

    return (
        <div className="flex items-center text-muted-alt">
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
            {isTestGroupForNewRefreshUX ? null : (
                <>
                    <span className="px-1">•</span>
                    <Tooltip title={insightRefreshButtonDisabledReason}>
                        <Button
                            type="link"
                            size="small"
                            onClick={() => loadData(true)}
                            disabled={!!insightRefreshButtonDisabledReason}
                            className="p-0"
                        >
                            <span className="text-sm">Refresh</span>
                        </Button>
                    </Tooltip>
                </>
            )}
        </div>
    )
}
