import { dayjs } from 'lib/dayjs'
import { kea } from 'kea'
import api from 'lib/api'
import { RETENTION_FIRST_TIME, RETENTION_RECURRING } from 'lib/constants'
import { range, toParams } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { isRetentionFilter } from 'scenes/insights/sharedUtils'
import { RetentionTablePayload, RetentionTablePeoplePayload, RetentionTrendPayload } from 'scenes/retention/types'
import { actionsModel } from '~/models/actionsModel'
import { Noun, groupsModel } from '~/models/groupsModel'
import { ActionType, InsightLogicProps, InsightType, RetentionFilterType } from '~/types'

export const dateOptions = ['Hour', 'Day', 'Week', 'Month']

// https://day.js.org/docs/en/durations/creating#list-of-all-available-units
const dateOptionToTimeIntervalMap = {
    Hour: 'h',
    Day: 'd',
    Week: 'w',
    Month: 'M',
}

export const dateOptionPlurals = {
    Hour: 'hours',
    Day: 'days',
    Week: 'weeks',
    Month: 'months',
}

export const retentionOptions = {
    [RETENTION_FIRST_TIME]: 'for the first time',
    [RETENTION_RECURRING]: 'recurringly',
}

export const retentionOptionDescriptions = {
    [`${RETENTION_RECURRING}`]: 'A user will belong to any cohort where they have performed the event in its Period 0.',
    [`${RETENTION_FIRST_TIME}`]:
        'A user will only belong to the cohort for which they performed the event for the first time.',
}

const DEFAULT_RETENTION_LOGIC_KEY = 'default_retention_key'

export const retentionLogic = kea({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps(DEFAULT_RETENTION_LOGIC_KEY),
    path: (key) => ['scenes', 'retention', 'retentionLogic', key],
    connect: (props: InsightLogicProps) => ({
        values: [
            insightLogic(props),
            ['filters as inflightFilters', 'insight', 'insightLoading'],
            actionsModel,
            ['actions'],
            groupsModel,
            ['aggregationLabel'],
        ],
        actions: [insightLogic(props), ['loadResultsSuccess']],
    }),
    actions: () => ({
        setFilters: (filters: Partial<RetentionFilterType>) => ({ filters }),
        setRetentionReference: (retentionReference: RetentionFilterType['retention_reference']) => ({
            retentionReference,
        }),
        loadMorePeople: true,
        updatePeople: (people: RetentionTablePeoplePayload) => ({ people }),
        clearPeople: true,
    }),
    loaders: ({ values }) => ({
        people: {
            __default: {} as RetentionTablePeoplePayload,
            loadPeople: async (rowIndex: number) => {
                const urlParams = toParams({ ...values.filters, selected_interval: rowIndex })
                return (await api.get(`api/person/retention/?${urlParams}`)) as RetentionTablePeoplePayload
            },
        },
    }),
    reducers: {
        people: {
            clearPeople: () => ({}),
            updatePeople: (_, { people }) => people,
        },
        loadingMore: [
            false,
            {
                loadMorePeople: () => true,
                updatePeople: () => false,
            },
        ],
    },
    selectors: {
        filters: [
            (s) => [s.inflightFilters],
            (inflightFilters): Partial<RetentionFilterType> =>
                inflightFilters && isRetentionFilter(inflightFilters) ? inflightFilters : {},
        ],
        loadedFilters: [
            (s) => [s.insight],
            ({ filters }): Partial<RetentionFilterType> => (filters && isRetentionFilter(filters) ? filters : {}),
        ],
        results: [
            // Take the insight result, and cast it to `RetentionTablePayload[]`
            (s) => [s.insight],
            ({ filters, result }): RetentionTablePayload[] => {
                return filters?.insight === InsightType.RETENTION ? result ?? [] : []
            },
        ],
        trendSeries: [
            (s) => [s.results, s.filters, s.retentionReference],
            (results, filters, retentionReference): RetentionTrendPayload[] => {
                // If the retention reference option is specified as previous,
                // then translate retention rates to relative to previous,
                // otherwise, just use what the result was originally.
                //
                // Our input results might looks something like
                //
                //   Cohort 1 | 1000 | 120 | 190 | 170 | 140
                //   Cohort 2 | 6003 | 300 | 100 | 120 | 50
                //
                // If `retentionReference` is not "previous" we want to calculate the percentages
                // of the sizes compared to the first value. If we have "previous" we want to
                // go further and translate these numbers into percentage of the previous value
                // so we get some idea for the rate of convergence.

                return results.map((cohortRetention, datasetIndex) => {
                    const retentionPercentages = cohortRetention.values
                        .map((value) => value.count / cohortRetention.values[0].count)
                        // Make them display in the right scale
                        .map((value) => (isNaN(value) ? 0 : 100 * value))

                    // To calculate relative percentages, we take for instance Cohort 1 as percentages
                    // of the cohort size and create another series that has a 100 at prepended so we have
                    //
                    //   Cohort 1'  | 100  | 12  | 19 | 17 | 14
                    //   Cohort 1'' | 100  | 100 | 12 | 19 | 17 | 14
                    //
                    // And from here construct a third, relative percentage series by dividing the
                    // top numbers by the bottom numbers to get
                    //
                    //   Cohort 1''' | 1 | 0.12 | ...
                    const paddedValues = [100].concat(retentionPercentages)

                    return {
                        id: datasetIndex,
                        days: retentionPercentages.map((_, index) => `${filters.period} ${index}`),
                        labels: retentionPercentages.map((_, index) => `${filters.period} ${index}`),
                        count: 0,
                        label: cohortRetention.date
                            ? filters.period === 'Hour'
                                ? dayjs(cohortRetention.date).format('MMM D, h A')
                                : dayjs.utc(cohortRetention.date).format('MMM D')
                            : cohortRetention.label,
                        data:
                            retentionReference === 'previous'
                                ? retentionPercentages
                                      // Zip together the current a previous values, filling
                                      // in with 100 for the first index
                                      .map((value, index) => [value, paddedValues[index]])
                                      // map values to percentage of previous
                                      .map(([value, previous]) => (100 * value) / previous)
                                : retentionPercentages,
                        index: datasetIndex,
                    }
                })
            },
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
        actionsLookup: [
            (s) => [s.actions],
            (actions: ActionType[]) => Object.assign({}, ...actions.map((action) => ({ [action.id]: action.name }))),
        ],
        retentionReference: [
            (selectors) => [selectors.filters],
            ({ retention_reference }) => retention_reference ?? 'total',
        ],
        aggregationTargetLabel: [
            (s) => [s.filters, s.aggregationLabel],
            (filters, aggregationLabel): Noun => {
                return aggregationLabel(filters.aggregation_group_type_index)
            },
        ],
        incompletenessOffsetFromEnd: [
            (s) => [s.filters, s.trendSeries],
            (filters, trendSeries) => {
                // Returns negative number of points to paint over starting from end of array
                if (!trendSeries?.[0]?.days) {
                    return 0
                } else if (!filters?.date_to) {
                    return -1
                }
                const numUnits = trendSeries[0].days.length
                const interval = dateOptionToTimeIntervalMap?.[filters.period ?? 'Day']
                const startDate = dayjs().startOf(interval)
                const startIndex = trendSeries[0].days.findIndex(
                    (_, i) => dayjs(filters?.date_to).add(i - numUnits, interval) >= startDate
                )

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - trendSeries[0].days.length
                } else {
                    return 0
                }
            },
        ],

        maxIntervalsCount: [
            (s) => [s.results],
            (results) => {
                return Math.max(...results.map((result) => result.values.length))
            },
        ],

        tableHeaders: [
            (s) => [s.results],
            (results) => {
                return ['Cohort', 'Size', ...results.map((x) => x.label)]
            },
        ],

        tableRows: [
            (s) => [s.results, s.maxIntervalsCount, s.filters],
            (results, maxIntervalsCount, { period, breakdowns }) => {
                return range(maxIntervalsCount).map((rowIndex: number) => [
                    // First column is the cohort label
                    breakdowns?.length
                        ? results[rowIndex].label
                        : period === 'Hour'
                        ? dayjs(results[rowIndex].date).format('MMM D, h A')
                        : dayjs.utc(results[rowIndex].date).format('MMM D'),
                    // Second column is the first value (which is essentially the total)
                    results[rowIndex].values[0].count,
                    // All other columns are rendered as percentage
                    ...results[rowIndex].values.map((row) => {
                        const percentage =
                            results[rowIndex].values[0]['count'] > 0
                                ? (row['count'] / results[rowIndex].values[0]['count']) * 100
                                : 0

                        return {
                            count: row['count'],
                            percentage,
                        }
                    }),
                ])
            },
        ],
    },
    listeners: ({ actions, values, props }) => ({
        setFilters: ({ filters }) => {
            insightLogic(props).actions.setFilters(cleanFilters({ ...values.filters, ...filters }, values.filters))
        },
        setRetentionReference: ({ retentionReference }) => {
            actions.setFilters({
                ...values.filters,
                // NOTE: we use lower case here to accommodate the expected
                // casing of the server
                retention_reference: retentionReference,
            })
        },
        loadResultsSuccess: async () => {
            actions.clearPeople()
        },
        loadMorePeople: async () => {
            if (values.people.next) {
                const peopleResult: RetentionTablePeoplePayload = await api.get(values.people.next)
                const newPeople: RetentionTablePeoplePayload = {
                    result: [...(values.people.result || []), ...(peopleResult.result || [])],
                    next: peopleResult.next,
                    missing_persons: (peopleResult.missing_persons || 0) + (values.people.missing_persons || 0),
                }
                actions.updatePeople(newPeople)
            }
        },
    }),
})
