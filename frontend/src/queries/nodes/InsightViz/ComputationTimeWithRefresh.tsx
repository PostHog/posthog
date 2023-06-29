import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { usePeriodicRerender } from 'lib/hooks/usePeriodicRerender'
import { dataNodeLogic } from '../DataNode/dataNodeLogic'

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { lastRefresh } = useValues(dataNodeLogic)

    usePeriodicRerender(15000)

    return (
        <div className="flex items-center text-muted-alt">
            Computed {lastRefresh ? dayjs(lastRefresh).fromNow() : 'a while ago'}
        </div>
    )
}
