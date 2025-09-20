import { kea, key, listeners, path, props, selectors } from 'kea'
import { lazyLoaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { Dayjs, now } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'
import { CalendarHeatMapProps } from 'scenes/web-analytics/CalendarHeatMap/CalendarHeatMap'

import { hogql } from '~/queries/utils'
import { ReplayTabs } from '~/types'

import type { replayActiveHoursHeatMapLogicType } from './replayActiveHoursHeatMapLogicType'

export interface ReplayActiveHoursHeatMapLogicProps {
    // we can show this component in different contexts, and key it accordingly
    scene?: 'templates' | 'filters' | 'replay-home'
}

const rowLabels = ['00:00 - 04:00', '04:00 - 08:00', '08:00 - 12:00', '12:00 - 16:00', '16:00 - 20:00', '20:00 - 00:00']

const columnLabels = (now: Dayjs): string[] => [
    now.subtract(6, 'day').format('ddd D'),
    now.subtract(5, 'day').format('ddd D'),
    now.subtract(4, 'day').format('ddd D'),
    now.subtract(3, 'day').format('ddd D'),
    now.subtract(2, 'day').format('ddd D'),
    now.subtract(1, 'day').format('ddd D'),
    'Today',
]

// does not need to be on the logic yet, since it's stateless for now
export const getOnClickTooltip = (colIndex: number, rowIndex: number | undefined): string => {
    const day = columnLabels(now())[colIndex]
    const timeRange = rowIndex === undefined ? undefined : rowLabels[rowIndex]
    return `View recordings for ${day}${timeRange ? ` ${timeRange}` : ''}`
}

// does not need to be on the logic yet, since it's stateless for now
export const onCellClick = (colIndex: number, rowIndex: number | undefined, timezone: string): void => {
    const daysToSubtract = 6 - colIndex
    let startDate = now().subtract(daysToSubtract, 'day').startOf('day').utc(true)
    let endDate = startDate.clone()

    if (rowIndex !== undefined) {
        const startHour = rowIndex * 4
        const endHour = startHour + 4
        startDate = startDate.hour(startHour)
        endDate = endDate.hour(endHour)
    } else {
        endDate = endDate.add(1, 'day')
    }

    posthog.capture('clicked_replay_active_hours_heatmap_cell', {
        isColumnHeader: rowIndex == undefined,
        isIndividualCell: rowIndex != undefined,
        timezone,
    })

    const setTimezoneWithoutChangingOtherValues = true
    router.actions.push(
        urls.replay(ReplayTabs.Home, {
            // here the browser might be in a different timezone to the project
            // but the dateTime has already been corrected so we need to set the timezone
            // but set `true` as the second parameter
            // this means we set the project timezone on the dayjs object
            // without changing the values
            date_from: startDate.tz(timezone, setTimezoneWithoutChangingOtherValues).toISOString(),
            date_to: endDate.tz(timezone, setTimezoneWithoutChangingOtherValues).toISOString(),
        })
    )
}

export const replayActiveHoursHeatMapLogic = kea<replayActiveHoursHeatMapLogicType>([
    path(['scenes', 'session-recordings', 'components', 'replayActiveHoursHeatMapLogic']),
    props({} as ReplayActiveHoursHeatMapLogicProps),
    key((props) => props.scene || 'default'),
    lazyLoaders(() => ({
        recordingsPerHour: {
            loadRecordingsPerHour: async (_, breakpoint): Promise<number[][]> => {
                const q = hogql`
                    SELECT hour_block,
                           countIf(_toDate(mints) = today() - 6) AS "Day -6",
                           countIf(_toDate(mints) = today() - 5) AS "Day -5",
                           countIf(_toDate(mints) = today() - 4) AS "Day -4",
                           countIf(_toDate(mints) = today() - 3) AS "Day -3",
                           countIf(_toDate(mints) = today() - 2) AS "Day -2",
                           countIf(_toDate(mints) = today() - 1) AS "Day -1",
                           countIf(_toDate(mints) = today())     AS "Day 0"
                    FROM (SELECT intDiv(toHour(mints), 4) * 4 AS real_hour_block,
                                 mints
                          FROM (SELECT min(min_first_timestamp) AS mints
                                FROM raw_session_replay_events
                                WHERE min_first_timestamp >= now() - INTERVAL 7 day
                                  AND min_first_timestamp <= now()
                                GROUP BY session_id
                                having dateDiff('SECOND'
                                     , min (min_first_timestamp)
                                     , max (max_last_timestamp))
                                     > 5)) AS data
                             RIGHT JOIN (SELECT arrayJoin([0, 4, 8, 12, 16, 20]) AS hour_block) AS hours
                                        ON data.real_hour_block = hours.hour_block
                    GROUP BY hour_block
                    ORDER BY hour_block`

                const qResponse = await api.queryHogQL(q)

                // this gives an array of arrays
                // we're loading hours 0-4, 4-8, 8-12, 12-16, 16-20, 20-24
                // so we get an array with 6 elements
                // each of those has 8 values
                // [0] is the hour block
                // and then each of the other 7 values is the count for that day

                breakpoint()

                return qResponse.results as number[][]
            },
        },
    })),
    selectors(() => ({
        calendarHeatmapProps: [
            (s) => [s.recordingsPerHour],
            (
                recordingsPerHour: number[][]
            ): Pick<CalendarHeatMapProps, 'rowLabels' | 'columnLabels' | 'processedData'> => {
                if (!recordingsPerHour || recordingsPerHour.length === 0 || recordingsPerHour[0].length === 0) {
                    return {
                        rowLabels: [],
                        columnLabels: [],
                        processedData: {
                            matrix: [],
                            columnsAggregations: [],
                            rowsAggregations: [],
                            overallValue: 0,
                            maxOverall: 0,
                            minOverall: 0,
                            maxRowAggregation: 0,
                            minRowAggregation: 0,
                            maxColumnAggregation: 0,
                            minColumnAggregation: 0,
                        },
                    }
                }

                const dataWithoutHourBlock = recordingsPerHour.map((row) => row.slice(1))

                const columnsAggregations = dataWithoutHourBlock.reduce((acc, row) => {
                    row.forEach((value: number, index: number) => {
                        acc[index] = (acc[index] || 0) + value
                    })
                    return acc
                }, [])
                const rowsAggregations = dataWithoutHourBlock.reduce((acc, row) => {
                    // take each row and ignoring row[0]
                    // gather a sum for each index in the row
                    // so we end up with an array of numbers with length 6
                    acc[row[0]] = (acc[row[0]] || 0) + row.reduce((a: number, b: number) => a + b, 0)
                    return acc
                }, [])
                const processedData = {
                    matrix: dataWithoutHourBlock,
                    columnsAggregations: columnsAggregations,
                    rowsAggregations: rowsAggregations,
                    overallValue: columnsAggregations.reduce((a: number, b: number) => a + b, 0),
                    maxOverall: dataWithoutHourBlock.reduce((acc, row) => {
                        return Math.max(acc, ...row)
                    }, 0),
                    minOverall: dataWithoutHourBlock.reduce((acc, row) => {
                        return Math.min(acc, ...row)
                    }, 0),
                    maxColumnAggregation: Math.max(...columnsAggregations),
                    minColumnAggregation: Math.min(...columnsAggregations),
                    maxRowAggregation: Math.max(...rowsAggregations),
                    minRowAggregation: Math.min(...rowsAggregations),
                }

                return {
                    rowLabels: rowLabels,
                    columnLabels: columnLabels(now()),
                    processedData: processedData,
                }
            },
        ],
        isClickable: [
            (s) => [s.calendarHeatmapProps],
            (calendarHeatmapProps) => (colIndex: number, rowIndex?: number) => {
                const valueSource =
                    rowIndex == undefined
                        ? calendarHeatmapProps?.processedData.columnsAggregations
                        : calendarHeatmapProps?.processedData.matrix[rowIndex]
                return (valueSource[colIndex] ?? 0) > 0
            },
        ],
    })),
    listeners(() => ({
        loadRecordingsPerHourFailed: async () => {
            lemonToast.error('Failed to load recordings activity for heatmap')
        },
    })),
])
