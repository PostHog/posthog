import { dashboard, dashboards, insight } from '../productAnalytics'
import { randomString } from '../support/random'

describe('Dashboard', () => {
    beforeEach(() => {
        cy.intercept('GET', /api\/projects\/\d+\/insights\/\?.*/).as('loadInsightList')
        cy.intercept('PATCH', /api\/projects\/\d+\/insights\/\d+\/.*/).as('patchInsight')
        cy.intercept('POST', /\/api\/projects\/\d+\/dashboards/).as('createDashboard')

        cy.clickNavMenu('dashboards')
        cy.location('pathname').should('include', '/dashboard')
    })

    it('Dashboards loaded', () => {
        cy.get('h1').should('contain', 'Dashboards')
        // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-organization]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-project]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-Dashboards]').should('have.text', 'Dashboards')
    })

    it('Adding new insight to dashboard works', () => {
        const dashboardName = randomString('Dashboard with matching filter')
        const insightName = randomString('insight to add to dashboard')

        // Create and visit a dashboard to get it into turbo mode cache
        dashboards.createAndGoToEmptyDashboard(dashboardName)

        insight.create(insightName)

        insight.addInsightToDashboard(dashboardName, { visitAfterAdding: true })

        cy.get('.CardMeta h4').should('have.text', insightName)

        dashboard.addPropertyFilter()
        cy.get('main').contains('There are no matching events for this query').should('not.exist')

        cy.clickNavMenu('dashboards')
        const dashboardNonMatching = randomString('Dashboard with non-matching filter')
        dashboards.createAndGoToEmptyDashboard(dashboardNonMatching)

        insight.visitInsight(insightName)
        insight.addInsightToDashboard(dashboardNonMatching, { visitAfterAdding: true })

        dashboard.addPropertyFilter('Browser', 'Hogbrowser')
        cy.get('main').contains('There are no matching events for this query').should('exist')

        // Go back and forth to make sure the filters are correctly applied
        for (let i = 0; i < 3; i++) {
            cy.clickNavMenu('dashboards')
            dashboards.visitDashboard(dashboardName)
            cy.get('.CardMeta h4').should('have.text', insightName)
            cy.get('h4').contains('Refreshing').should('not.exist')
            cy.get('main').contains('There are no matching events for this query').should('not.exist')

            cy.clickNavMenu('dashboards')
            dashboards.visitDashboard(dashboardNonMatching)
            cy.get('.CardMeta h4').should('have.text', insightName)
            cy.get('h4').contains('Refreshing').should('not.exist')
            cy.get('main').contains('There are no matching events for this query').should('exist')
        }
    })

    it('Refreshing dashboard works', () => {
        const dashboardName = randomString('Dashboard with insights')
        const insightName = randomString('insight to add to dashboard')

        // Create and visit a dashboard to get it into turbo mode cache
        dashboards.createAndGoToEmptyDashboard(dashboardName)

        insight.create(insightName)

        insight.addInsightToDashboard(dashboardName, { visitAfterAdding: true })

        cy.get('.CardMeta h4').should('have.text', insightName)
        cy.get('h4').contains('Refreshing').should('not.exist')
        cy.get('main').contains('There are no matching events for this query').should('not.exist')

        // intercept cache query
        // /api/projects/1/query/cache_d7c9854c5e2a1a655343ea481ec2b55f/

        cy.intercept('GET', /\/api\/projects\/\d+\/dashboard_templates/, (req) => {
            req.reply((response) => {
                response.body.results[0].variables = [
                    {
                        id: 'id',
                        name: 'Unique variable name',
                        type: 'event',
                        default: {},
                        required: true,
                        description: 'description',
                    },
                ]
                return response
            })
        })
        /* {
            "query_status": {
                "complete": false,
                "dashboard_id": 48,
                "end_time": null,
                "error": false,
                "error_message": null,
                "expiration_time": "2024-07-30T12:21:18.795Z",
                "id": "cache_d7c9854c5e2a1a655343ea481ec2b55f",
                "insight_id": 59,
                "labels": [],
                "pickup_time": null,
                "query_async": true,
                "query_progress": null,
                "results": null,
                "start_time": "2024-07-30T12:01:18.795Z",
                "task_id": "61b3cbad-d831-4a21-a690-737fb8bc2dc1",
                "team_id": 1
            } */

        /*
                {
    "query_status": {
        "complete": true,
        "dashboard_id": 3,
        "end_time": "2024-07-30T12:06:42.955Z",
        "error": false,
        "error_message": null,
        "expiration_time": "2024-07-30T12:26:42.730Z",
        "id": "cache_a88e585312d389654e43b3ed6bef5c73",
        "insight_id": 10,
        "labels": [
            "chained"
        ],
        "pickup_time": "2024-07-30T12:06:42.730Z",
        "query_async": true,
        "query_progress": null,
        "results": {
            "cache_key": "cache_a88e585312d389654e43b3ed6bef5c73",
            "cache_target_age": "2024-07-30T14:06:42.741080Z",
            "calculation_trigger": "chaining",
            "error": "",
            "hogql": "SELECT\n    sum(total) AS total,\n    if(ifNull(greaterOrEquals(row_number, 26), 0), '$$_posthog_breakdown_other_$$', breakdown_value) AS breakdown_value\nFROM\n    (SELECT\n        count AS total,\n        breakdown_value AS breakdown_value,\n        row_number() OVER (ORDER BY total DESC) AS row_number\n    FROM\n        (SELECT\n            sum(total) AS count,\n            breakdown_value\n        FROM\n            (SELECT\n                count() AS total,\n                ifNull(nullIf(toString(properties.$current_url), ''), '$$_posthog_breakdown_null_$$') AS breakdown_value\n            FROM\n                events AS e SAMPLE 1\n            WHERE\n                and(greaterOrEquals(timestamp, toStartOfDay(assumeNotNull(toDateTime('2024-07-29 00:00:00')))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-07-29 23:59:59'))), equals(event, '$pageview'), notILike(properties.$current_url, '%/files/%'))\n            GROUP BY\n                breakdown_value)\n        GROUP BY\n            breakdown_value\n        ORDER BY\n            breakdown_value ASC)\n    ORDER BY\n        total DESC,\n        breakdown_value ASC)\nWHERE\n    notEquals(breakdown_value, NULL)\nGROUP BY\n    breakdown_value\nORDER BY\n    if(equals(breakdown_value, '$$_posthog_breakdown_other_$$'), 2, if(equals(breakdown_value, '$$_posthog_breakdown_null_$$'), 1, 0)) ASC,\n    total DESC,\n    breakdown_value ASC\nLIMIT 50000",
            "is_cached": false,
            "last_refresh": "2024-07-30T12:06:42.741080Z",
            "modifiers": {
                "bounceRatePageViewMode": "count_pageviews",
                "dataWarehouseEventsModifiers": [],
                "debug": null,
                "inCohortVia": "auto",
                "materializationMode": "legacy_null_as_null",
                "optimizeJoinedFilters": false,
                "personsArgMaxVersion": "auto",
                "personsJoinMode": null,
                "personsOnEventsMode": "disabled",
                "s3TableUseInvalidColumns": null,
                "sessionTableVersion": "auto"
            },
            "next_allowed_client_refresh": "2024-07-30T12:09:42.741080Z",
            "query_status": null,
            "results": [
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 11,
                    "label": "http://localhost:8000/project/1/dashboard/3",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1/dashboard/3"
                },
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 8,
                    "label": "http://localhost:8000/project/1/insights/yGQaFv6q",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1/insights/yGQaFv6q"
                },
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 7,
                    "label": "http://localhost:8000/project/1/dashboard",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1/dashboard"
                },
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 5,
                    "label": "http://localhost:8000/project/1",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1"
                },
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 3,
                    "label": "http://localhost:8000/project/1/dashboard/1",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1/dashboard/1"
                },
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 2,
                    "label": "http://localhost:8000/project/1/dashboard/2",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1/dashboard/2"
                },
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 1,
                    "label": "http://localhost:8000/project/1/insights",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1/insights"
                },
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 1,
                    "label": "http://localhost:8000/project/1/insights/oDF9CPf1",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1/insights/oDF9CPf1"
                },
                {
                    "data": [],
                    "days": [],
                    "count": 0,
                    "aggregated_value": 1,
                    "label": "http://localhost:8000/project/1/notebooks",
                    "filter": {
                        "insight": "TRENDS",
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "AND",
                                    "values": [
                                        {
                                            "key": "$current_url",
                                            "label": null,
                                            "operator": "not_icontains",
                                            "type": "event",
                                            "value": "/files/"
                                        }
                                    ]
                                }
                            ]
                        },
                        "filter_test_accounts": false,
                        "date_to": "2024-07-29T23:59:59.999999Z",
                        "date_from": "2024-07-29T00:00:00Z",
                        "entity_type": "events",
                        "interval": "day",
                        "aggregationAxisFormat": "numeric",
                        "display": "ActionsTable",
                        "showLegend": false,
                        "showPercentStackView": false,
                        "showValuesOnSeries": false,
                        "smoothingIntervals": 1,
                        "breakdown": "$current_url",
                        "breakdown_type": "event"
                    },
                    "action": {
                        "days": [
                            "2024-07-29T00:00:00Z"
                        ],
                        "id": "$pageview",
                        "type": "events",
                        "order": 0,
                        "name": "$pageview",
                        "custom_name": null,
                        "math": "total",
                        "math_property": null,
                        "math_hogql": null,
                        "math_group_type_index": null,
                        "properties": {}
                    },
                    "breakdown_value": "http://localhost:8000/project/1/notebooks"
                }
            ],
            "timezone": "UTC",
            "timings": [
                {
                    "k": "./trends_to_query",
                    "t": 0.01827837500604801
                },
                {
                    "k": "./printing_hogql_for_response",
                    "t": 0.0342049169994425
                },
                {
                    "k": "./execute_queries/series_0/query",
                    "t": 7.95800588093698e-06
                },
                {
                    "k": "./execute_queries/series_0/replace_placeholders",
                    "t": 9.291697642765939e-05
                },
                {
                    "k": "./execute_queries/series_0/max_limit",
                    "t": 6.665999535471201e-06
                },
                {
                    "k": "./execute_queries/series_0/hogql/prepare_ast/clone",
                    "t": 0.00012041599256917834
                },
                {
                    "k": "./execute_queries/series_0/hogql/prepare_ast/create_hogql_database",
                    "t": 0.0399777079874184
                },
                {
                    "k": "./execute_queries/series_0/hogql/prepare_ast/resolve_types",
                    "t": 0.0015273330209311098
                },
                {
                    "k": "./execute_queries/series_0/hogql/prepare_ast",
                    "t": 0.04167833301471546
                },
                {
                    "k": "./execute_queries/series_0/hogql/print_ast/printer",
                    "t": 0.00029370898846536875
                },
                {
                    "k": "./execute_queries/series_0/hogql/print_ast",
                    "t": 0.0003236250195186585
                },
                {
                    "k": "./execute_queries/series_0/hogql",
                    "t": 0.04201108298730105
                },
                {
                    "k": "./execute_queries/series_0/print_ast/create_hogql_database",
                    "t": 0.03737316600745544
                },
                {
                    "k": "./execute_queries/series_0/print_ast/resolve_types",
                    "t": 0.001080832997104153
                },
                {
                    "k": "./execute_queries/series_0/print_ast/resolve_property_types",
                    "t": 0.0022457919840235263
                },
                {
                    "k": "./execute_queries/series_0/print_ast/resolve_lazy_tables",
                    "t": 0.0007607080042362213
                },
                {
                    "k": "./execute_queries/series_0/print_ast/swap_properties",
                    "t": 0.00022887499653734267
                },
                {
                    "k": "./execute_queries/series_0/print_ast/printer",
                    "t": 0.0005586249753832817
                },
                {
                    "k": "./execute_queries/series_0/print_ast",
                    "t": 0.04232358300941996
                },
                {
                    "k": "./execute_queries/series_0/clickhouse_execute",
                    "t": 0.047950125008355826
                },
                {
                    "k": "./execute_queries/series_0",
                    "t": 0.1324460839969106
                },
                {
                    "k": "./execute_queries",
                    "t": 0.1583062089921441
                },
                {
                    "k": ".",
                    "t": 0.22084916700259782
                }
            ]
        },
        "start_time": "2024-07-30T12:06:42.482Z",
        "task_id": "88262e7e-2e63-4ab4-a4aa-af211ed43bb9",
        "team_id": 1
    }
}
                 */

        // refresh the dashboard by changing date range
        cy.get('[data-attr="date-filter"]').click()
        cy.contains('span', 'Last 14 days').click()
        cy.contains('span', 'Apply and save dashboard').click()

        cy.contains('span[class="text-primary text-sm font-medium"]', 'Refreshing').should('not.exist')
        cy.get('span').contains('Refreshing').should('not.exist')
    })

    it('Shows details when moving between dashboard and insight', () => {
        const dashboardName = randomString('Dashboard')
        const insightName = randomString('DashboardInsight')

        // Create and visit a dashboard to get it into turbo mode cache
        dashboards.createAndGoToEmptyDashboard(dashboardName)

        insight.create(insightName)

        insight.addInsightToDashboard(dashboardName, { visitAfterAdding: true })

        // Put a second insight on a dashboard, visit both insights a few times to make sure they show data still
        const insightNameOther = randomString('DashboardInsightOther')
        insight.create(insightNameOther)
        insight.addInsightToDashboard(dashboardName, { visitAfterAdding: true })

        cy.reload()

        cy.get('.CardMeta h4').contains(insightName).click()
        cy.get('.Insight').should('contain', 'Last modified').wait(500)
        cy.go('back').wait(500)

        cy.get('.CardMeta h4').contains(insightNameOther).click()
        cy.get('.Insight').should('contain', 'Last modified').wait(500)
        cy.go('back').wait(500)

        cy.get('.CardMeta h4').contains(insightName).click()
        cy.get('.Insight').should('contain', 'Last modified').wait(500)
    })

    it('Dashboard filter updates are correctly isolated for one insight on multiple dashboards', () => {
        const dashboardAName = randomString('Dashboard with insight A')
        const dashboardBName = randomString('Dashboard with insight B')
        const insightName = randomString('insight to add to dashboard')

        // Create and visit two dashboards to get them into turbo mode cache
        dashboards.createAndGoToEmptyDashboard(dashboardAName)
        cy.clickNavMenu('dashboards')
        dashboards.createAndGoToEmptyDashboard(dashboardBName)

        insight.create(insightName)

        // Add that one insight to both dashboards
        insight.addInsightToDashboard(dashboardAName, { visitAfterAdding: false })
        cy.get('[aria-label="close"]').click()
        insight.addInsightToDashboard(dashboardBName, { visitAfterAdding: false })
        cy.get('[aria-label="close"]').click()

        // Let's get dashboard A mounted
        cy.clickNavMenu('dashboards')
        dashboards.visitDashboard(dashboardAName)
        cy.get('[data-attr=date-filter]').contains('No date range override')
        cy.get('.InsightCard h5').should('have.length', 1).contains('Last 7 days')
        // Now let's see dashboard B
        cy.clickNavMenu('dashboards')
        dashboards.visitDashboard(dashboardBName)
        cy.get('[data-attr=date-filter]').contains('No date range override')
        cy.get('.InsightCard h5').should('have.length', 1).contains('Last 7 days')
        // Override the time range on dashboard B
        cy.get('[data-attr=date-filter]').contains('No date range override').click()
        cy.get('div').contains('Yesterday').should('exist').click()
        cy.get('[data-attr=date-filter]').contains('Yesterday')
        cy.get('button').contains('Apply and save dashboard').click()
        cy.get('.InsightCard h5').should('have.length', 1).contains('Yesterday')
        // Cool, now back to A and make sure the insight is still using the original range there, not the one from B
        cy.clickNavMenu('dashboards')
        dashboards.visitDashboard(dashboardAName)
        cy.get('[data-attr=date-filter]').contains('No date range override')
        cy.get('.InsightCard h5').should('have.length', 1).contains('Last 7 days') // This must not be "Yesterday"!
    })

    it('Adding new insight to dashboard does not clear filters', () => {
        const dashboardName = randomString('to add an insight to')
        const firstInsight = randomString('insight to add to dashboard')
        const secondInsight = randomString('another insight to add to dashboard')

        // Create and visit a dashboard to get it into turbo mode cache
        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(firstInsight)

        dashboard.addAnyFilter()

        dashboard.addInsightToEmptyDashboard(secondInsight)

        cy.get('.PropertyFilterButton').should('have.length', 1)

        cy.get('.CardMeta h4').should('contain.text', firstInsight)
        cy.get('.CardMeta h4').should('contain.text', secondInsight)
    })

    it('Cannot see tags or description (non-FOSS feature)', () => {
        cy.get('h1').should('contain', 'Dashboards')
        cy.get('th').contains('Description').should('not.exist')
        cy.get('th').contains('Tags').should('not.exist')

        cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
        cy.get('.InsightCard').should('exist')
        cy.get('.dashboard-description').should('not.exist')
        cy.get('[data-attr=dashboard-tags]').should('not.exist')
    })

    it('Pinned dashboards on menu', () => {
        cy.clickNavMenu('activity') // to make sure the dashboards menu item is not the active one
        cy.get('[data-attr=menu-item-pinned-dashboards-dropdown]').click()
        cy.get('.Popover').should('be.visible')
        cy.get('.Popover a').should('contain', 'App Analytics')
    })

    it('Create an empty dashboard', () => {
        const dashboardName = 'New Dashboard 2'

        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr="create-dashboard-blank"]').click()
        cy.get('[data-attr="top-bar-name"]').should('exist')
        cy.get('[data-attr="top-bar-name"] button').click()
        cy.get('[data-attr="top-bar-name"] input').clear().type(dashboardName).blur()

        cy.contains(dashboardName).should('exist')
        cy.get('.EmptyDashboard').should('exist')

        // Check that dashboard is not pinned by default
        cy.get('.TopBar3000 [data-attr="dashboard-three-dots-options-menu"]').click()
        cy.get('button').contains('Pin dashboard').should('exist')
    })

    it('Create dashboard from a template', () => {
        const TEST_DASHBOARD_NAME = 'XDefault'

        dashboards.createDashboardFromDefaultTemplate(TEST_DASHBOARD_NAME)

        cy.get('.InsightCard').its('length').should('be.gte', 2)
        // Breadcrumbs work
        cy.get('[data-attr=breadcrumb-organization]').should('contain', 'Hogflix')
        cy.get('[data-attr=breadcrumb-project]').should('contain', 'Hogflix Demo App')
        cy.get('[data-attr=breadcrumb-Dashboards]').should('have.text', 'Dashboards')
        cy.get('[data-attr^="breadcrumb-Dashboard:"]').should('have.text', TEST_DASHBOARD_NAME + 'UnnamedCancelSave')
    })

    const assertVariablesConfigurationScreenIsShown = (): void => {
        cy.get('[data-attr="new-dashboard-chooser"]').contains('Unique variable name').should('exist')
    }

    it('Allow reselecting a dashboard after pressing back', () => {
        cy.intercept('GET', /\/api\/projects\/\d+\/dashboard_templates/, (req) => {
            req.reply((response) => {
                response.body.results[0].variables = [
                    {
                        id: 'id',
                        name: 'Unique variable name',
                        type: 'event',
                        default: {},
                        required: true,
                        description: 'description',
                    },
                ]
                return response
            })
        })

        // Request templates again.
        cy.clickNavMenu('dashboards')

        cy.get('[data-attr="new-dashboard"]').click()
        cy.get('[data-attr="create-dashboard-from-template"]').click()
        assertVariablesConfigurationScreenIsShown()

        cy.contains('.LemonButton', 'Back').click()

        cy.get('[data-attr="create-dashboard-from-template"]').click()
        assertVariablesConfigurationScreenIsShown()
    })

    it('Click on a dashboard item dropdown and view graph', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('a').contains('View').click()
        cy.location('pathname').should('include', '/insights')
    })

    it('Rename dashboard item', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('button').contains('Rename').click()

        cy.get('[data-attr=insight-name]').clear().type('Test Name')
        cy.contains('Submit').click()
        cy.contains('Test Name').should('exist')
    })

    it('Color dashboard item', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('button').contains('Set color').click()
        cy.get('button').contains('Green').click()
        cy.get('.InsightCard .CardMeta__ribbon').should('have.class', 'green')
    })

    it('Duplicate dashboard item', () => {
        cy.get('[data-attr=dashboard-name]').contains('Web Analytics').click()
        cy.get('.InsightCard [data-attr=more-button]').first().click()
        cy.get('button').contains('Duplicate').click()
        cy.get('[data-attr=success-toast]').contains('Insight duplicated').should('exist')
    })

    it('Move dashboard item', () => {
        cy.intercept('PATCH', /api\/projects\/\d+\/dashboards\/\d+\/move_tile.*/).as('moveTile')

        const sourceDashboard = randomString('source-dashboard')
        const targetDashboard = randomString('target-dashboard')
        const insightToMove = randomString('insight-to-move')
        dashboards.createAndGoToEmptyDashboard(sourceDashboard)
        const insightToLeave = randomString('insight-to-leave')
        dashboard.addInsightToEmptyDashboard(insightToLeave)
        dashboard.addInsightToEmptyDashboard(insightToMove)

        cy.wait(200)

        // create the target dashboard and get it cached by turbo-mode
        cy.clickNavMenu('dashboards')
        dashboards.createAndGoToEmptyDashboard(targetDashboard)

        cy.clickNavMenu('dashboards')
        dashboards.visitDashboard(sourceDashboard)

        cy.contains('.InsightCard ', insightToMove).within(() => {
            cy.get('[data-attr=more-button]').first().click({ force: true })
        })

        cy.get('button').contains('Move to').click()
        cy.get('button').contains(targetDashboard).click()

        cy.wait('@moveTile').then(() => {
            cy.get('.CardMeta h4').should('have.text', insightToLeave)

            cy.clickNavMenu('dashboards')
            dashboards.visitDashboard(targetDashboard)
            cy.get('.CardMeta h4').should('have.text', insightToMove)
        })
    })

    /**
     * This test is currently failing because the query that runs when you open the dashboard includes the code
     * select equals(replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, 'app_rating'), ''), 'null'), '^"|"$', ''), 5.) from events where event ilike '%rated%';
     * This throws the error Code: 386. DB::Exception: There is no supertype for types String, Float64 because some of them are String/FixedString and some of them are not. (NO_COMMON_TYPE)
     * All the 'app_ratings' are extracted as strings and 5. is a float
     */
    // it('Opens dashboard item in insights', () => {
    //     cy.get('[data-attr=dashboard-name]').contains('App Analytics').click()
    //     cy.get('.InsightCard [data-attr=insight-card-title]').first().click()
    //     cy.location('pathname').should('include', '/insights')
    //     cy.get('[data-attr=funnel-bar-vertical]', { timeout: 30000 }).should('exist')
    // })

    it('Add insight from empty dashboard', () => {
        const dashboardName = randomString('dashboard-')
        dashboards.createAndGoToEmptyDashboard(dashboardName)
        dashboard.addInsightToEmptyDashboard(randomString('insight-'))

        cy.wait(200)
        cy.get('[data-attr="top-bar-name"] .EditableField__display').contains(dashboardName).should('exist')
    })
})
