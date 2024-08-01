import { urls } from 'scenes/urls'

describe('insights date picker', () => {
    beforeEach(() => {
        cy.visit(urls.insightNew())
    })

    it('Can set the date filter and show the right grouping interval', () => {
        cy.intercept('**/query/', (req) =>
            req.reply({
                cache_key: 'cache_a4afa59a719dd561ac65162bbf7f8191',
                query_status: {
                    complete: false,
                    dashboard_id: null,
                    end_time: null,
                    error: false,
                    error_message: null,
                    expiration_time: '2024-08-01T07:47:19.403856Z',
                    id: '88f9169a-e7c8-4267-bf12-908933d639d9',
                    insight_id: null,
                    labels: null,
                    pickup_time: null,
                    query_async: true,
                    query_progress: null,
                    results: null,
                    start_time: '2024-08-01T07:27:19.364304Z',
                    task_id: 'e1b5e6de-a09c-4108-accc-c82fe0e551d4',
                    team_id: 1,
                },
            })
        )
        cy.intercept('**/query/88f9169a-e7c8-4267-bf12-908933d639d9/', (req) =>
            req.reply({
                query_status: {
                    complete: true,
                    dashboard_id: null,
                    end_time: '2024-08-01T07:27:19.743Z',
                    error: false,
                    error_message: null,
                    expiration_time: '2024-08-01T07:47:19.389Z',
                    id: '88f9169a-e7c8-4267-bf12-908933d639d9',
                    insight_id: null,
                    labels: null,
                    pickup_time: '2024-08-01T07:27:19.389Z',
                    query_async: true,
                    query_progress: null,
                    results: {
                        cache_key: 'cache_a4afa59a719dd561ac65162bbf7f8191',
                        cache_target_age: '2024-08-01T07:42:19.404498Z',
                        calculation_trigger: null,
                        error: '',
                        hogql: "SELECT\n    arrayMap(number -> plus(toStartOfHour(assumeNotNull(toDateTime('2024-07-31 00:00:00'))), toIntervalHour(number)), range(0, plus(coalesce(dateDiff('hour', toStartOfHour(assumeNotNull(toDateTime('2024-07-31 00:00:00'))), toStartOfHour(assumeNotNull(toDateTime('2024-07-31 23:59:59'))))), 1))) AS date,\n    arrayMap(_match_date -> arraySum(arraySlice(groupArray(count), indexOf(groupArray(day_start) AS _days_for_count, _match_date) AS _index, plus(minus(arrayLastIndex(x -> equals(x, _match_date), _days_for_count), _index), 1))), date) AS total_array,\n    arrayMap(i -> floor(arrayAvg(arraySlice(total_array, greatest(plus(minus(i, 24), 1), 1), least(i, 24)))), arrayEnumerate(total_array)) AS total\nFROM\n    (SELECT\n        sum(total) AS count,\n        day_start\n    FROM\n        (SELECT\n            count() AS total,\n            toStartOfHour(timestamp) AS day_start\n        FROM\n            events AS e SAMPLE 1\n        WHERE\n            and(greaterOrEquals(timestamp, assumeNotNull(toDateTime('2024-07-31 00:00:00'))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-07-31 23:59:59'))), equals(event, '$pageview'))\n        GROUP BY\n            day_start)\n    GROUP BY\n        day_start\n    ORDER BY\n        day_start ASC)\nORDER BY\n    arraySum(total) DESC\nLIMIT 50000",
                        is_cached: false,
                        last_refresh: '2024-08-01T07:27:19.404498Z',
                        modifiers: {
                            bounceRatePageViewMode: 'count_pageviews',
                            dataWarehouseEventsModifiers: [],
                            debug: null,
                            inCohortVia: 'auto',
                            materializationMode: 'legacy_null_as_null',
                            optimizeJoinedFilters: false,
                            personsArgMaxVersion: 'auto',
                            personsJoinMode: null,
                            personsOnEventsMode: 'person_id_override_properties_joined',
                            s3TableUseInvalidColumns: null,
                            sessionTableVersion: 'auto',
                        },
                        next_allowed_client_refresh: '2024-08-01T07:30:19.404498Z',
                        query_status: null,
                        results: [
                            {
                                data: [
                                    0.0, 0.0, 19.0, 35.0, 51.0, 47.0, 41.0, 36.0, 32.0, 29.0, 27.0, 24.0, 22.0, 21.0,
                                    19.0, 18.0, 17.0, 16.0, 15.0, 14.0, 14.0, 13.0, 12.0, 12.0,
                                ],
                                labels: [
                                    '31-Jul-2024 00:00',
                                    '31-Jul-2024 01:00',
                                    '31-Jul-2024 02:00',
                                    '31-Jul-2024 03:00',
                                    '31-Jul-2024 04:00',
                                    '31-Jul-2024 05:00',
                                    '31-Jul-2024 06:00',
                                    '31-Jul-2024 07:00',
                                    '31-Jul-2024 08:00',
                                    '31-Jul-2024 09:00',
                                    '31-Jul-2024 10:00',
                                    '31-Jul-2024 11:00',
                                    '31-Jul-2024 12:00',
                                    '31-Jul-2024 13:00',
                                    '31-Jul-2024 14:00',
                                    '31-Jul-2024 15:00',
                                    '31-Jul-2024 16:00',
                                    '31-Jul-2024 17:00',
                                    '31-Jul-2024 18:00',
                                    '31-Jul-2024 19:00',
                                    '31-Jul-2024 20:00',
                                    '31-Jul-2024 21:00',
                                    '31-Jul-2024 22:00',
                                    '31-Jul-2024 23:00',
                                ],
                                days: [
                                    '2024-07-31 00:00:00',
                                    '2024-07-31 01:00:00',
                                    '2024-07-31 02:00:00',
                                    '2024-07-31 03:00:00',
                                    '2024-07-31 04:00:00',
                                    '2024-07-31 05:00:00',
                                    '2024-07-31 06:00:00',
                                    '2024-07-31 07:00:00',
                                    '2024-07-31 08:00:00',
                                    '2024-07-31 09:00:00',
                                    '2024-07-31 10:00:00',
                                    '2024-07-31 11:00:00',
                                    '2024-07-31 12:00:00',
                                    '2024-07-31 13:00:00',
                                    '2024-07-31 14:00:00',
                                    '2024-07-31 15:00:00',
                                    '2024-07-31 16:00:00',
                                    '2024-07-31 17:00:00',
                                    '2024-07-31 18:00:00',
                                    '2024-07-31 19:00:00',
                                    '2024-07-31 20:00:00',
                                    '2024-07-31 21:00:00',
                                    '2024-07-31 22:00:00',
                                    '2024-07-31 23:00:00',
                                ],
                                count: 534.0,
                                label: '$pageview',
                                filter: {
                                    insight: 'TRENDS',
                                    properties: [],
                                    filter_test_accounts: false,
                                    date_to: '2024-07-31T23:59:59.999999-04:00',
                                    date_from: '2024-07-31T00:00:00-04:00',
                                    entity_type: 'events',
                                    interval: 'hour',
                                    aggregationAxisFormat: 'numeric',
                                    display: 'ActionsLineGraph',
                                    showLegend: false,
                                    showPercentStackView: false,
                                    showValuesOnSeries: false,
                                    smoothingIntervals: 24,
                                },
                                action: {
                                    days: [
                                        '2024-07-31T00:00:00-04:00',
                                        '2024-07-31T01:00:00-04:00',
                                        '2024-07-31T02:00:00-04:00',
                                        '2024-07-31T03:00:00-04:00',
                                        '2024-07-31T04:00:00-04:00',
                                        '2024-07-31T05:00:00-04:00',
                                        '2024-07-31T06:00:00-04:00',
                                        '2024-07-31T07:00:00-04:00',
                                        '2024-07-31T08:00:00-04:00',
                                        '2024-07-31T09:00:00-04:00',
                                        '2024-07-31T10:00:00-04:00',
                                        '2024-07-31T11:00:00-04:00',
                                        '2024-07-31T12:00:00-04:00',
                                        '2024-07-31T13:00:00-04:00',
                                        '2024-07-31T14:00:00-04:00',
                                        '2024-07-31T15:00:00-04:00',
                                        '2024-07-31T16:00:00-04:00',
                                        '2024-07-31T17:00:00-04:00',
                                        '2024-07-31T18:00:00-04:00',
                                        '2024-07-31T19:00:00-04:00',
                                        '2024-07-31T20:00:00-04:00',
                                        '2024-07-31T21:00:00-04:00',
                                        '2024-07-31T22:00:00-04:00',
                                        '2024-07-31T23:00:00-04:00',
                                    ],
                                    id: '$pageview',
                                    type: 'events',
                                    order: 0,
                                    name: '$pageview',
                                    custom_name: null,
                                    math: 'total',
                                    math_property: null,
                                    math_hogql: null,
                                    math_group_type_index: null,
                                    properties: {},
                                },
                            },
                        ],
                        timezone: 'America/Aruba',
                        timings: [
                            {
                                k: './trends_to_query',
                                t: 0.07540899992454797,
                            },
                            {
                                k: './printing_hogql_for_response',
                                t: 0.07724100002087653,
                            },
                            {
                                k: './execute_queries/series_0/query',
                                t: 3.999995533376932e-5,
                            },
                            {
                                k: './execute_queries/series_0/replace_placeholders',
                                t: 0.00020208291243761778,
                            },
                            {
                                k: './execute_queries/series_0/max_limit',
                                t: 1.4208024367690086e-5,
                            },
                            {
                                k: './execute_queries/series_0/hogql/prepare_ast/clone',
                                t: 0.00024341593962162733,
                            },
                            {
                                k: './execute_queries/series_0/hogql/prepare_ast/create_hogql_database',
                                t: 0.07117899996228516,
                            },
                            {
                                k: './execute_queries/series_0/hogql/prepare_ast/resolve_types',
                                t: 0.0010180840035900474,
                            },
                            {
                                k: './execute_queries/series_0/hogql/prepare_ast',
                                t: 0.07250270794611424,
                            },
                            {
                                k: './execute_queries/series_0/hogql/print_ast/printer',
                                t: 0.0004343339242041111,
                            },
                            {
                                k: './execute_queries/series_0/hogql/print_ast',
                                t: 0.0004849169636145234,
                            },
                            {
                                k: './execute_queries/series_0/hogql',
                                t: 0.07300345902331173,
                            },
                            {
                                k: './execute_queries/series_0/print_ast/create_hogql_database',
                                t: 0.07186625001486391,
                            },
                            {
                                k: './execute_queries/series_0/print_ast/resolve_types',
                                t: 0.0014092499623075128,
                            },
                            {
                                k: './execute_queries/series_0/print_ast/resolve_property_types',
                                t: 0.0006202079821377993,
                            },
                            {
                                k: './execute_queries/series_0/print_ast/resolve_lazy_tables',
                                t: 0.0008000420639291406,
                            },
                            {
                                k: './execute_queries/series_0/print_ast/swap_properties',
                                t: 0.0003186659887433052,
                            },
                            {
                                k: './execute_queries/series_0/print_ast/printer',
                                t: 0.0007185410941019654,
                            },
                            {
                                k: './execute_queries/series_0/print_ast',
                                t: 0.07584125001449138,
                            },
                            {
                                k: './execute_queries/series_0/clickhouse_execute',
                                t: 0.033433042000979185,
                            },
                            {
                                k: './execute_queries/series_0',
                                t: 0.18266566703096032,
                            },
                            {
                                k: './execute_queries',
                                t: 0.18366091698408127,
                            },
                            {
                                k: '.',
                                t: 0.3507570830406621,
                            },
                        ],
                    },
                    start_time: '2024-08-01T07:27:19.364Z',
                    task_id: null,
                    team_id: 1,
                },
            })
        )

        cy.get('[data-attr=date-filter]').click()
        cy.get('div').contains('Yesterday').should('exist').click()
        cy.get('[data-attr=interval-filter] .LemonButton__content').should('contain', 'hour')
    })

    it('Can set a custom rolling date range', () => {
        cy.get('[data-attr=date-filter]').click()
        cy.get('.Popover [data-attr=rolling-date-range-input]').type('{selectall}5{enter}')
        cy.get('.Popover [data-attr=rolling-date-range-date-options-selector]').click()
        cy.get('.RollingDateRangeFilter__popover > div').contains('days').should('exist').click()
        cy.get('.Popover .RollingDateRangeFilter__label').should('contain', 'In the last').click()

        // Test that the button shows the correct formatted range
        cy.get('[data-attr=date-filter]').get('.LemonButton__content').contains('Last 5 days').should('exist')
    })
})
