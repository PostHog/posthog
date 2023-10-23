import { useState } from 'react'
import { AnyResponseType, WebOverviewStatsQuery, WebOverviewStatsQueryResponse } from '~/queries/schema'
import { useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { isNotNil } from 'lib/utils'
import { IconTrendingDown, IconTrendingFlat, IconTrendingUp } from 'lib/lemon-ui/icons'
import { getColorVar } from 'lib/colors'

let uniqueNode = 0

export function WebOverviewStatsTable(props: {
    query: WebOverviewStatsQuery
    cachedResults?: AnyResponseType
}): JSX.Element | null {
    const [key] = useState(() => `WebOverviewStats.${uniqueNode++}`)
    const logic = dataNodeLogic({ query: props.query, key, cachedResults: props.cachedResults })
    const { response, responseLoading } = useValues(logic)

    if (responseLoading) {
        return (
            <div className="w-full flex flex-col items-center text-2xl">
                <Spinner />
            </div>
        )
    }

    if (!response) {
        return null
    }

    const results = (response as WebOverviewStatsQueryResponse | undefined)?.results

    return (
        <div className="w-full flex flex-row flex-wrap justify-between space-y-2">
            {results?.map((item) => {
                const trend = isNotNil(item.changeFromPreviousPct)
                    ? item.changeFromPreviousPct === 0
                        ? { C: IconTrendingFlat, color: getColorVar('muted') }
                        : item.changeFromPreviousPct > 0
                        ? {
                              C: IconTrendingUp,
                              color: !item.isIncreaseBad ? getColorVar('success') : getColorVar('danger'),
                          }
                        : {
                              C: IconTrendingDown,
                              color: !item.isIncreaseBad ? getColorVar('danger') : getColorVar('success'),
                          }
                    : undefined

                const value = item.value.toLocaleString()

                return (
                    <div key={item.key} className="min-w-40 h-20 flex flex-col items-center text-center">
                        <div className="font-bold uppercase text-xs">{item.key}</div>
                        <div className="w-full flex-1 items-center justify-center">
                            <div className={value.length > 7 ? 'text-2xl' : value.length > 4 ? 'text-4xl' : 'text-6xl'}>
                                {value}
                            </div>
                        </div>
                        {trend && (
                            // eslint-disable-next-line react/forbid-dom-props
                            <div style={{ color: trend.color }}>
                                <trend.C color={trend.color} /> {item.changeFromPreviousPct}%
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
