import type { LemonSegmentedButtonOption } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isDefinitionStale } from 'lib/utils/definitions'

import {
    DateRange,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignee,
    ErrorTrackingSparklineConfig,
} from '~/queries/schema/schema-general'
import { EventDefinitionType, FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import type { errorTrackingLogicType } from './errorTrackingLogicType'

const lastHour = { value: '1h', label: '1h' }
const lastDay = { value: '24h', label: '24h' }
const lastMonth = { value: 'mStart', label: 'Month' }
const lastYear = { value: 'yStart', label: 'Year' }

export type SparklineOption = LemonSegmentedButtonOption<string>

const customOptions: Record<string, { custom: SparklineOption; default: SparklineOption }> = {
    // ordering of the keys is important here
    // the shorter period should always be on the rhs
    // this will maintain the order when we call Object.values()
    // to render the options in the sparkline header
    dStart: { default: lastDay, custom: lastHour }, // today
    '-24h': { default: lastDay, custom: lastHour },
    mStart: { custom: lastMonth, default: lastDay },
    yStart: { custom: lastYear, default: lastMonth },
    all: { custom: lastYear, default: lastMonth },
}

export const DEFAULT_ERROR_TRACKING_DATE_RANGE = { date_from: '-7d', date_to: null }

export const DEFAULT_ERROR_TRACKING_FILTER_GROUP = {
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: [] }],
}

export const SPARKLINE_CONFIGURATIONS: Record<string, ErrorTrackingSparklineConfig> = {
    '1h': { value: 60, interval: 'minute' },
    '24h': { value: 24, interval: 'hour' },
    '7d': { value: 168, interval: 'hour' }, // 7d * 24h = 168h
    '14d': { value: 336, interval: 'hour' }, // 14d * 24h = 336h
    '90d': { value: 90, interval: 'day' },
    '180d': { value: 26, interval: 'week' }, // 180d / 7d = 26 weeks
    mStart: { value: 31, interval: 'day' },
    yStart: { value: 52, interval: 'week' },
}

export function constructSparklineConfig(selectedPeriod: string): ErrorTrackingSparklineConfig | null {
    if (selectedPeriod in SPARKLINE_CONFIGURATIONS) {
        return SPARKLINE_CONFIGURATIONS[selectedPeriod]
    }

    const [value, unit] = selectedPeriod.match(/\d+|\D+/g) as RegExpMatchArray
    return {
        value: Number(value) * (unit === 'y' ? 12 : 1),
        interval: unit === 'h' ? 'hour' : unit === 'd' ? 'day' : unit === 'w' ? 'week' : 'month',
    }
}

export const errorTrackingLogic = kea<errorTrackingLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingLogic']),

    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setAssignee: (assignee: ErrorTrackingIssue['assignee']) => ({ assignee }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setSparklineSelectedPeriod: (period: string | null) => ({ period }),
    }),
    reducers({
        dateRange: [
            DEFAULT_ERROR_TRACKING_DATE_RANGE as DateRange,
            { persist: true },
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        assignee: [
            null as ErrorTrackingIssueAssignee | null,
            {
                setAssignee: (_, { assignee }) => assignee,
            },
        ],
        filterGroup: [
            DEFAULT_ERROR_TRACKING_FILTER_GROUP as UniversalFiltersGroup,
            { persist: true },
            {
                setFilterGroup: (_, { filterGroup }) => filterGroup,
            },
        ],
        filterTestAccounts: [
            false as boolean,
            { persist: true },
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
            },
        ],
        searchQuery: [
            '' as string,
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        sparklineSelectedPeriod: [
            lastDay.value as string | null,
            { persist: true },
            {
                setSparklineSelectedPeriod: (_, { period }) => period,
            },
        ],
    }),
    loaders({
        hasSentExceptionEvent: {
            __default: undefined as boolean | undefined,
            loadExceptionEventDefinition: async (): Promise<boolean> => {
                const exceptionDefinition = await api.eventDefinitions.list({
                    event_type: EventDefinitionType.Event,
                    search: '$exception',
                })
                const definition = exceptionDefinition.results.find((r) => r.name === '$exception')
                return definition ? !isDefinitionStale(definition) : false
            },
        },
    }),
    selectors({
        sparklineOptions: [
            (s) => [s.dateRange],
            ({ date_from }): { custom: SparklineOption; default: SparklineOption } | null => {
                if (!date_from) {
                    return null
                }

                const isRelative = date_from.match(/-\d+[hdmy]/)
                if (date_from in customOptions) {
                    return customOptions[date_from]
                } else if (isRelative) {
                    const value = date_from?.replace('-', '')
                    return { custom: { value: value, label: value }, default: lastDay }
                }
                return null
            },
        ],
        customSparklineConfig: [
            (s) => [s.sparklineOptions],
            (sparklineOptions): ErrorTrackingSparklineConfig | null =>
                sparklineOptions ? constructSparklineConfig(sparklineOptions.custom.value) : null,
        ],
    }),
    subscriptions(({ values, actions }) => ({
        sparklineOptions: (sparklineOptions: { custom: SparklineOption; default: SparklineOption } | null) => {
            if (!sparklineOptions) {
                actions.setSparklineSelectedPeriod(null)
            } else {
                const options = Object.values(sparklineOptions).map((o) => o.value)
                const validOption = values.sparklineSelectedPeriod && options.includes(values.sparklineSelectedPeriod)

                if (!validOption) {
                    actions.setSparklineSelectedPeriod(sparklineOptions.custom.value)
                }
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExceptionEventDefinition()
    }),
])
