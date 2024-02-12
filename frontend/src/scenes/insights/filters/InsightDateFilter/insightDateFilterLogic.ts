import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { InsightLogicProps } from '~/types'

import type { insightDateFilterLogicType } from './insightDateFilterLogicType'

export const insightDateFilterLogic = kea<insightDateFilterLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'InsightDateFilter', 'insightDateFilterLogic', key]),
    connect((props: InsightLogicProps) => ({
        actions: [insightVizDataLogic(props), ['updateQuerySource']],
        values: [insightVizDataLogic(props), ['dateRange']],
    })),
    actions(() => ({
        setDates: (dateFrom: string | undefined | null, dateTo: string | undefined | null) => ({
            dateFrom,
            dateTo,
        }),
    })),
    selectors({
        dates: [
            (s) => [s.dateRange],
            (dateRange) => ({ dateFrom: dateRange?.date_from || null, dateTo: dateRange?.date_to || null }),
        ],
    }),
    listeners(({ actions }) => ({
        setDates: ({ dateFrom, dateTo }) => {
            actions.updateQuerySource({
                dateRange: {
                    date_from: dateFrom || null,
                    date_to: dateTo || null,
                },
            })
        },
    })),
])
