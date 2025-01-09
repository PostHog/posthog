import { actions, kea, path, reducers } from 'kea'
import { getDefaultInterval, updateDatesWithInterval } from 'lib/utils'

import { IntervalType } from '~/types'

import type { llmObservabilityLogicType } from './llmObservabilityLogicType'

export const LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID = 'llm-observability'

const INITIAL_DATE_FROM = '-24h' as string | null
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL = getDefaultInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

export const llmObservabilityLogic = kea<llmObservabilityLogicType>([
    path(['scenes', 'llm-observability', 'llmObservabilityLogic']),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
    }),
    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
                interval: INITIAL_INTERVAL,
            },
            persistConfig,
            {
                setDates: (_, { dateTo, dateFrom }) => ({
                    dateTo,
                    dateFrom,
                    interval: getDefaultInterval(dateFrom, dateTo),
                }),
                setInterval: ({ dateFrom: oldDateFrom, dateTo: oldDateTo }, { interval }) => {
                    const { dateFrom, dateTo } = updateDatesWithInterval(interval, oldDateFrom, oldDateTo)
                    return {
                        dateTo,
                        dateFrom,
                        interval,
                    }
                },
                setDatesAndInterval: (_, { dateTo, dateFrom, interval }) => {
                    if (!dateFrom && !dateTo) {
                        dateFrom = INITIAL_DATE_FROM
                        dateTo = INITIAL_DATE_TO
                    }
                    return {
                        dateTo,
                        dateFrom,
                        interval: interval || getDefaultInterval(dateFrom, dateTo),
                    }
                },
            },
        ],
        shouldFilterTestAccounts: [
            false,
            persistConfig,
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
            },
        ],
    }),
])
