export const grafanaClassic = {
    dashboard: {
        title: 'Checkout service',
        time: { from: 'now-24h', to: 'now' },
        refresh: '30s',
        timezone: 'utc',
        templating: {
            list: [
                { type: 'datasource', name: 'DS', query: 'prometheus' },
                { type: 'custom', name: 'region', query: 'eu,us', current: { value: 'eu' } },
            ],
        },
        panels: [
            {
                type: 'stat',
                title: 'Success rate',
                gridPos: { x: 0, y: 0, w: 6, h: 5 },
                datasource: { uid: '${DS}' },
                fieldConfig: { defaults: { unit: 'percentunit' } },
                targets: [
                    {
                        refId: 'A',
                        expr: 'sum(rate(checkout_ok_total[$__rate_interval])) / sum(rate(checkout_total[$__rate_interval]))',
                    },
                ],
            },
            {
                type: 'timeseries',
                title: 'Requests by route',
                gridPos: { x: 6, y: 0, w: 18, h: 8 },
                datasource: { type: 'prometheus', uid: 'prom' },
                targets: [
                    {
                        refId: 'A',
                        expr: 'sum by (route) (rate(http_requests_total{region="$region"}[$__interval]))',
                        legendFormat: '{{route}}',
                    },
                    {
                        refId: 'B',
                        expr: 'sum(rate(http_requests_total{region="$region"}[5m]))',
                        legendFormat: 'all',
                        hide: true,
                    },
                ],
            },
            { type: 'row', title: 'Errors', collapsed: false, gridPos: { x: 0, y: 8, w: 24, h: 1 } },
            {
                type: 'barchart',
                title: 'Errors by code',
                gridPos: { x: 0, y: 9, w: 12, h: 8 },
                targets: [
                    { refId: 'A', expr: 'sum by (code) (increase(http_errors_total[1h]))', legendFormat: '__auto' },
                ],
            },
            {
                type: 'timeseries',
                title: 'Error logs',
                gridPos: { x: 12, y: 9, w: 12, h: 8 },
                datasource: { type: 'loki', uid: 'logs' },
                targets: [
                    {
                        refId: 'A',
                        expr: 'sum by (pod) (count_over_time({namespace="shop"} |= "error" [5m]))',
                        legendFormat: '{{pod}}',
                    },
                ],
            },
            {
                type: 'row',
                title: 'Database',
                collapsed: true,
                gridPos: { x: 0, y: 17, w: 24, h: 1 },
                panels: [
                    {
                        type: 'table',
                        title: 'Slow queries',
                        gridPos: { x: 0, y: 18, w: 12, h: 8 },
                        datasource: { type: 'grafana-clickhouse-datasource', uid: 'ch' },
                        targets: [{ refId: 'A', rawSql: 'SELECT query FROM slow_log LIMIT 10' }],
                    },
                    {
                        type: 'heatmap',
                        title: 'Latency',
                        gridPos: { x: 12, y: 18, w: 12, h: 8 },
                        targets: [{ refId: 'A', expr: 'sum by (le) (rate(db_latency_bucket[5m]))' }],
                    },
                ],
            },
            {
                type: 'text',
                title: 'Runbook',
                gridPos: { x: 0, y: 26, w: 24, h: 2 },
                options: { content: 'Page the **checkout** owner.' },
            },
        ],
    },
}

const v2Panel = (title: string, viz: string, expr: string): object => ({
    kind: 'Panel',
    spec: {
        title,
        vizConfig: { group: viz, spec: { options: {} } },
        data: {
            kind: 'QueryGroup',
            spec: {
                queries: [
                    {
                        kind: 'PanelQuery',
                        spec: {
                            refId: 'A',
                            query: {
                                kind: 'DataQuery',
                                group: 'prometheus',
                                datasource: { name: 'metrics' },
                                spec: { expr, legendFormat: 'p{{p}}' },
                            },
                        },
                    },
                ],
            },
        },
    },
})
const gridItem = (name: string, x: number, y: number, width: number, height: number): object => ({
    kind: 'GridLayoutItem',
    spec: { element: { kind: 'ElementReference', name }, x, y, width, height },
})

export const grafanaV2 = {
    apiVersion: 'dashboard.grafana.app/v2',
    kind: 'Dashboard',
    metadata: { name: 'queue-health' },
    spec: {
        title: 'Queue health',
        timeSettings: { from: 'now-6h', to: 'now', autoRefresh: '1m', timezone: 'utc' },
        variables: [
            {
                kind: 'QueryVariable',
                spec: {
                    name: 'service',
                    includeAll: true,
                    current: { value: ['worker-a', 'worker-b'] },
                    query: { group: 'prometheus', spec: { query: 'label_values(service)' } },
                },
            },
        ],
        elements: {
            depth: v2Panel('Queue depth', 'timeseries', 'sum(queue_depth{service=~"$service"})'),
            spread: v2Panel(
                'Lag spread',
                'timeseries',
                'quantiles("p", 0.5, 0.9, max_over_time(queue_lag_seconds[$__interval]))'
            ),
            logs: v2Panel('Worker logs', 'logs', 'sum(rate(queue_events_total[5m]))'),
        },
        layout: {
            kind: 'TabsLayout',
            spec: {
                tabs: [
                    {
                        kind: 'TabsLayoutTab',
                        spec: {
                            title: 'Overview',
                            layout: { kind: 'GridLayout', spec: { items: [gridItem('depth', 0, 0, 24, 8)] } },
                        },
                    },
                    {
                        kind: 'TabsLayoutTab',
                        spec: {
                            title: 'Details',
                            layout: {
                                kind: 'RowsLayout',
                                spec: {
                                    rows: [
                                        {
                                            kind: 'RowsLayoutRow',
                                            spec: {
                                                title: 'Lag',
                                                collapse: true,
                                                layout: {
                                                    kind: 'GridLayout',
                                                    spec: {
                                                        items: [
                                                            gridItem('spread', 0, 0, 12, 8),
                                                            gridItem('logs', 12, 0, 12, 8),
                                                        ],
                                                    },
                                                },
                                            },
                                        },
                                    ],
                                },
                            },
                        },
                    },
                ],
            },
        },
    },
}
