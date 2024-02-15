import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { getColorVar } from 'lib/colors'
import { IconTrendingDown, IconTrendingFlat, IconTrendingUp } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration, humanFriendlyLargeNumber, isNotNil, range } from 'lib/utils'
import { useState } from 'react'

import { EvenlyDistributedRows } from '~/queries/nodes/WebOverview/EvenlyDistributedRows'
import { AnyResponseType, WebOverviewItem, WebOverviewQuery, WebOverviewQueryResponse } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

const OVERVIEW_ITEM_CELL_MIN_WIDTH_REMS = 10

const OVERVIEW_ITEM_CELL_CLASSES = `flex-1 border p-2 bg-bg-light rounded min-w-[${OVERVIEW_ITEM_CELL_MIN_WIDTH_REMS}rem] h-30 flex flex-col items-center text-center justify-between`

let uniqueNode = 0
export function WebOverview(props: {
    query: WebOverviewQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `WebOverview.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })
    const { response, responseLoading } = useValues(logic)

    const webOverviewQueryResponse = response as WebOverviewQueryResponse | undefined

    const samplingRate = webOverviewQueryResponse?.samplingRate

    return (
        <>
            <EvenlyDistributedRows
                className="flex justify-center items-center flex-wrap w-full gap-2"
                minWidthRems={OVERVIEW_ITEM_CELL_MIN_WIDTH_REMS + 2}
            >
                {responseLoading
                    ? range(5).map((i) => <WebOverviewItemCellSkeleton key={i} />)
                    : webOverviewQueryResponse?.results?.map((item) => (
                          <WebOverviewItemCell key={item.key} item={item} />
                      )) || []}
                {}
            </EvenlyDistributedRows>
            {samplingRate && !(samplingRate.numerator === 1 && (samplingRate.denominator ?? 1) === 1) ? (
                <LemonBanner type="info" className="my-4">
                    These results using a sampling factor of {samplingRate.numerator}
                    {samplingRate.denominator ?? 1 !== 1 ? `/${samplingRate.denominator}` : ''}. Sampling is currently
                    in beta.
                </LemonBanner>
            ) : null}
        </>
    )
}

const WebOverviewItemCellSkeleton = (): JSX.Element => {
    return (
        <div className={OVERVIEW_ITEM_CELL_CLASSES}>
            <LemonSkeleton className="h-2 w-10" />

            <LemonSkeleton />
        </div>
    )
}

const WebOverviewItemCell = ({ item }: { item: WebOverviewItem }): JSX.Element => {
    const label = labelFromKey(item.key)
    const trend = isNotNil(item.changeFromPreviousPct)
        ? item.changeFromPreviousPct === 0
            ? { Icon: IconTrendingFlat, color: getColorVar('muted') }
            : item.changeFromPreviousPct > 0
            ? {
                  Icon: IconTrendingUp,
                  color: !item.isIncreaseBad ? getColorVar('success') : getColorVar('danger'),
              }
            : {
                  Icon: IconTrendingDown,
                  color: !item.isIncreaseBad ? getColorVar('danger') : getColorVar('success'),
              }
        : undefined

    // If current === previous, say "increased by 0%"
    const tooltip =
        isNotNil(item.value) && isNotNil(item.previous) && isNotNil(item.changeFromPreviousPct)
            ? `${label}: ${item.value >= item.previous ? 'increased' : 'decreased'} by ${formatPercentage(
                  Math.abs(item.changeFromPreviousPct),
                  { precise: true }
              )}, to ${formatItem(item.value, item.kind, { precise: true })} from ${formatItem(
                  item.previous,
                  item.kind,
                  { precise: true }
              )}`
            : isNotNil(item.value)
            ? `${label}: ${formatItem(item.value, item.kind, { precise: true })}`
            : 'No data'

    return (
        <Tooltip title={tooltip}>
            <div className={OVERVIEW_ITEM_CELL_CLASSES}>
                <div className="font-bold uppercase text-xs">{label}</div>
                <div className="w-full flex-1 flex items-center justify-center">
                    <div className="text-2xl">{formatItem(item.value, item.kind)}</div>
                </div>
                {trend && isNotNil(item.changeFromPreviousPct) ? (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div style={{ color: trend.color }}>
                        <trend.Icon color={trend.color} /> {formatPercentage(item.changeFromPreviousPct)}
                    </div>
                ) : (
                    <div />
                )}
            </div>
        </Tooltip>
    )
}

const formatPercentage = (x: number, options?: { precise?: boolean }): string => {
    if (options?.precise) {
        return (x / 100).toLocaleString(undefined, { style: 'percent', maximumFractionDigits: 1 })
    } else if (x >= 1000) {
        return humanFriendlyLargeNumber(x) + '%'
    } else {
        return (x / 100).toLocaleString(undefined, { style: 'percent', maximumFractionDigits: 0 })
    }
}

const formatSeconds = (x: number): string => humanFriendlyDuration(Math.round(x))

const formatUnit = (x: number, options?: { precise?: boolean }): string => {
    if (options?.precise) {
        return x.toLocaleString()
    } else {
        return humanFriendlyLargeNumber(x)
    }
}

const formatItem = (
    value: number | undefined,
    kind: WebOverviewItem['kind'],
    options?: { precise?: boolean }
): string => {
    if (value == null) {
        return '-'
    } else if (kind === 'percentage') {
        return formatPercentage(value, options)
    } else if (kind === 'duration_s') {
        return formatSeconds(value)
    } else {
        return formatUnit(value, options)
    }
}

const labelFromKey = (key: string): string => {
    switch (key) {
        case 'visitors':
            return 'Visitors'
        case 'views':
            return 'Views'
        case 'sessions':
            return 'Sessions'
        case 'session duration':
            return 'Session Duration'
        case 'bounce rate':
            return 'Bounce Rate'
        default:
            return key
                .split(' ')
                .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ')
    }
}
