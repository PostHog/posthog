import React, { useCallback, useEffect, useRef, useState } from 'react'
import { AnyResponseType, WebOverviewStatsQuery, WebOverviewStatsQueryResponse } from '~/queries/schema'
import { useValues } from 'kea'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { isNotNil } from 'lib/utils'
import { IconTrendingDown, IconTrendingFlat, IconTrendingUp } from 'lib/lemon-ui/icons'
import { getColorVar } from 'lib/colors'
import prettyMilliseconds from 'pretty-ms'
import millify from 'millify'
import clsx from 'clsx'

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
        <EvenlyDistributedRows className="w-full gap-2" minWidthRems={12}>
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

                let value: string
                if (item.value == null) {
                    value = '-'
                } else if (item.kind === 'percentage') {
                    value = formatPercentage(item.value)
                } else if (item.kind === 'duration_s') {
                    value = formatSeconds(item.value)
                } else {
                    value = formatCount(item.value)
                }

                return (
                    <div
                        key={item.key}
                        className="min-w-40 min-h-20 flex-1 flex flex-col items-center text-center justify-between"
                    >
                        <div className="font-bold uppercase text-xs">{item.key}</div>
                        <div className="w-full flex-1 flex items-center justify-center">
                            <div className="text-2xl">{value}</div>
                        </div>
                        {trend && isNotNil(item.changeFromPreviousPct) ? (
                            // eslint-disable-next-line react/forbid-dom-props
                            <div style={{ color: trend.color }}>
                                <trend.C color={trend.color} /> {formatPercentage(item.changeFromPreviousPct)}
                            </div>
                        ) : (
                            <div />
                        )}
                    </div>
                )
            }) || []}
        </EvenlyDistributedRows>
    )
}

export const EvenlyDistributedRows = ({
    children,
    minWidthRems,
    className,
}: {
    children: React.ReactNode[]
    minWidthRems: number
    className: string
}): JSX.Element => {
    const [rowLayout, setRowLayout] = useState<{ itemsPerRow: number; numRows: number }>()
    const elementRef = useRef<HTMLDivElement>(null)

    const updateSize = useCallback((): void => {
        if (!elementRef.current) {
            return
        }
        const pxPerRem = parseFloat(getComputedStyle(document.documentElement).fontSize)
        const minWidthPx = minWidthRems * pxPerRem
        const containerWidthPx = elementRef.current.offsetWidth

        const maxItemsPerRow = Math.floor(containerWidthPx / minWidthPx)
        // Distribute items evenly
        // e.g. if we can have 4 elements per row and have 9 items
        // prefer 3,3,3 to 4,4,1
        const numRows = Math.ceil(children.length / maxItemsPerRow)
        const itemsPerRow = Math.ceil(children.length / numRows)

        setRowLayout({
            numRows,
            itemsPerRow,
        })
    }, [setRowLayout, elementRef, minWidthRems, children.length])

    useEffect(() => {
        const element = elementRef.current
        if (!element) {
            return
        }

        updateSize()

        let resizeObserver: ResizeObserver | undefined
        if (typeof ResizeObserver !== 'undefined') {
            resizeObserver = new ResizeObserver(updateSize)
        }
        resizeObserver?.observe(element)

        return () => {
            resizeObserver?.unobserve(element)
        }
    }, [updateSize])

    return (
        <div
            className={clsx('grid', className)}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ gridTemplateColumns: `repeat(${rowLayout?.itemsPerRow ?? 1}, 1fr)` }}
            ref={elementRef}
        >
            {rowLayout ? children : null}
        </div>
    )
}

const formatPercentage = (x: number): string => {
    if (x >= 1000) {
        return millify(x) + '%'
    } else {
        return Math.round(x) + '%'
    }
}

const formatSeconds = (x: number): string => prettyMilliseconds(Math.round(x) * 1000)

const formatCount = (x: number): string => millify(x)
