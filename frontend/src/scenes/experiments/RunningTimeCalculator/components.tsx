import { IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils'

import { TIMEFRAME_HISTORICAL_DATA_DAYS } from './runningTimeCalculatorLogic'

export const UniqueUsersPanel = ({ uniqueUsers }: { uniqueUsers: number }): JSX.Element => {
    if (!uniqueUsers) {
        return <></>
    }

    return (
        <div>
            <div className="card-secondary">Unique users</div>
            <div className="font-semibold">~{humanFriendlyNumber(uniqueUsers, 0)} persons</div>
            <div className="text-xs text-muted">Last {TIMEFRAME_HISTORICAL_DATA_DAYS} days</div>
        </div>
    )
}

export const AverageEventsPerUserPanel = ({ averageEventsPerUser }: { averageEventsPerUser: number }): JSX.Element => {
    if (!averageEventsPerUser) {
        return <></>
    }

    return (
        <div>
            <div className="card-secondary">Avg. events per user</div>
            <div className="font-semibold">~{humanFriendlyNumber(averageEventsPerUser, 0)}</div>
        </div>
    )
}

export const AveragePropertyValuePerUserPanel = ({
    averagePropertyValuePerUser,
}: {
    averagePropertyValuePerUser: number
}): JSX.Element => {
    if (!averagePropertyValuePerUser) {
        return <></>
    }

    return (
        <div>
            <div className="card-secondary">Avg. property value per user</div>
            <div className="font-semibold">~{humanFriendlyNumber(averagePropertyValuePerUser, 0)}</div>
        </div>
    )
}

export const StandardDeviationPanel = ({ standardDeviation }: { standardDeviation: number | null }): JSX.Element => {
    if (!standardDeviation) {
        return <></>
    }

    return (
        <div>
            <div className="card-secondary">
                <span>Est. standard deviation</span>
                <Tooltip
                    className="ml-1"
                    title={
                        <>
                            The estimated standard deviation of the metric in the last 14 days. It's the
                            "human-readable" version of the amount of dispersion in the dataset, and is calculated as
                            the square root of the variance. The variance informs the recommended sample size.
                        </>
                    }
                >
                    <IconInfo className="text-secondary ml-1" />
                </Tooltip>
            </div>
            <div className="font-semibold">~{humanFriendlyNumber(standardDeviation, 0)}</div>
        </div>
    )
}
