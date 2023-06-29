import { useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { dataNodeLogic } from '../DataNode/dataNodeLogic'

export function ComputationTimeWithRefresh(): JSX.Element | null {
    const { lastRefresh } = useValues(dataNodeLogic)

    if (!lastRefresh) {
        return null
    }

    return <div className="flex items-center text-muted-alt">Computed {dayjs(lastRefresh).fromNow()}</div>
}
