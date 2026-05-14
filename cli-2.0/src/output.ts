import chalk from 'chalk'
import { highlight } from 'cli-highlight'
import Table from 'cli-table3'
import { run as runJq } from 'node-jq'
import { createRequire } from 'node:module'

import {
    bucketAverage,
    bucketLabels,
    buildLabelRow,
    CHARTABLE_INSIGHT_TOOLS,
    type ChartSeries,
    formatYValue,
    friendlyBreakdownLabel,
    getInsightType,
    getPostHogHex,
    hexToAnsi,
    isChartSeries,
    isRecord,
    type JsonRecord,
    maxRenderablePoints,
    pickStep,
    stringify,
    widenSeries,
} from './insight-display.js'

type TableColumn = {
    header: string
    render: (item: JsonRecord) => string
}

type AsciiChart = {
    blue: string
    green: string
    yellow: string
    magenta: string
    cyan: string
    red: string
    plot: (
        series: number[] | number[][],
        options: { height: number; colors: string[]; format: (value: number) => string }
    ) => string
}

type Chartscii = {
    new (data: number[], options?: { 
        width?: number
        height?: number
        color?: string
        sort?: boolean
        reverse?: boolean
        naked?: boolean
        colorIndex?: number
        theme?: any
    }): {
        create(): string
    }
}

const require = createRequire(import.meta.url)
let cachedAsciichart: AsciiChart | null | undefined
let cachedChartscii: Chartscii | null | undefined

function getAsciichart(): AsciiChart | undefined {
    if (cachedAsciichart !== undefined) {
        return cachedAsciichart ?? undefined
    }

    try {
        // asciichart is a CommonJS module, use it directly.
        const module = require('asciichart') as AsciiChart
        cachedAsciichart = module
    } catch {
        cachedAsciichart = null
    }

    return cachedAsciichart ?? undefined
}

function getChartscii(): Chartscii | undefined {
    if (cachedChartscii !== undefined) {
        return cachedChartscii ?? undefined
    }

    try {
        const module = require('chartscii') as { Chartscii: Chartscii } | { default: { Chartscii: Chartscii } }
        cachedChartscii = 'Chartscii' in module ? module.Chartscii : module.default.Chartscii
    } catch {
        cachedChartscii = null
    }

    return cachedChartscii ?? undefined
}

function isBarChartData(result: unknown): boolean {
    if (!isRecord(result)) return false
    
    // Check if this is explicitly a bar chart visualization
    if (isRecord(result.query) && isRecord(result.query.source) && isRecord(result.query.source.trendsFilter)) {
        const display = result.query.source.trendsFilter.display
        return display === 'ActionsBarValue' || display === 'ActionsBar'
    }
    
    return false
}

function convertToBarChartSeries(result: unknown): ChartSeries[] {
    if (!isRecord(result) || !Array.isArray(result.result)) {
        return []
    }

    // Collect, translate sentinel labels (Other / None), and sort by value desc
    // so the largest bar renders at the top — matches the web rendering.
    const buckets: Array<{ value: number; label: string }> = []
    for (const item of result.result) {
        if (isRecord(item) && typeof item.aggregated_value === 'number' && item.label !== undefined) {
            buckets.push({ value: item.aggregated_value, label: friendlyBreakdownLabel(item.label) })
        }
    }

    if (buckets.length === 0) {
        return []
    }

    buckets.sort((a, b) => b.value - a.value)

    return [
        {
            data: buckets.map((b) => b.value),
            labels: buckets.map((b) => b.label),
            label: stringify(result.name) || stringify(result.derived_name) || 'Bar Chart',
            count: buckets.reduce((sum, b) => sum + b.value, 0),
        },
    ]
}

function shouldUseBarChart(series: ChartSeries[]): boolean {
    if (series.length === 0) return false
    
    // Use bar charts for categorical data with fewer data points
    const firstSeries = series[0]
    const points = firstSeries.data.length
    
    // If there are relatively few data points (≤ 10), consider using bar chart
    // Also check if labels look like categories rather than time series
    if (points <= 10) {
        const labels = firstSeries.labels.map(l => stringify(l).toLowerCase())
        // Check if labels look like categories (not dates/times)
        const hasDateLike = labels.some(label => 
            /\d{4}-\d{2}-\d{2}/.test(label) || // ISO date
            /\d{1,2}[-\/]\d{1,2}/.test(label) || // MM/DD or DD/MM
            /jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec/.test(label) // month names
        )
        return !hasDateLike
    }
    
    return false
}

function getListItems(result: unknown): JsonRecord[] {
    if (Array.isArray(result)) {
        return result.filter(isRecord)
    }

    if (isRecord(result) && Array.isArray(result.results)) {
        return result.results.filter(isRecord)
    }

    return []
}

function getResultCount(result: unknown): number | undefined {
    if (!isRecord(result) || typeof result.count !== 'number') {
        return undefined
    }

    return result.count
}

function truncate(value: string, maxLength: number): string {
    if (value.length <= maxLength) {
        return value
    }

    return `${value.slice(0, maxLength - 1)}…`
}

function printHighlightedJson(json: string): void {
    if (!process.stdout.isTTY) {
        console.log(json)
        return
    }
    console.log(highlight(json, { language: 'json', ignoreIllegals: true }))
}

function printPrettyJson(result: unknown): void {
    printHighlightedJson(JSON.stringify(result, null, 2))
}

function printListTable(result: unknown, emptyMessage: string, columns: TableColumn[]): void {
    if (!process.stdout.isTTY) {
        printPrettyJson(result)
        return
    }

    const items = getListItems(result)

    if (items.length === 0) {
        console.log(chalk.gray(emptyMessage))
        return
    }

    const table = new Table({
        head: columns.map((column) => column.header),
        wordWrap: true,
        wrapOnWordBoundary: false,
    })

    for (const item of items) {
        table.push(columns.map((column) => column.render(item)))
    }

    console.log(table.toString())

    const count = getResultCount(result)
    if (count !== undefined && count !== items.length) {
        console.log(chalk.gray(`Showing ${items.length} of ${count}`))
    }
}

function printFeatureFlags(result: unknown): void {
    printListTable(result, 'No feature flags found.', [
        { header: 'ID', render: (flag) => stringify(flag.id) },
        { header: 'Key', render: (flag) => truncate(stringify(flag.key), 40) },
        { header: 'Name', render: (flag) => truncate(stringify(flag.name), 60) },
        {
            header: 'Status',
            render: (flag) => (flag.active ? chalk.green('active') : chalk.gray('inactive')),
        },
    ])
}

function printInsights(result: unknown): void {
    printListTable(result, 'No insights found.', [
        { header: 'ID', render: (insight) => stringify(insight.id) },
        { header: 'Short ID', render: (insight) => stringify(insight.short_id) },
        { header: 'Name', render: (insight) => truncate(stringify(insight.name), 60) },
        { header: 'Type', render: (insight) => stringify(isRecord(insight.query) ? insight.query.kind : '') },
    ])
}

function printDashboards(result: unknown): void {
    printListTable(result, 'No dashboards found.', [
        { header: 'ID', render: (dashboard) => stringify(dashboard.id) },
        { header: 'Name', render: (dashboard) => truncate(stringify(dashboard.name), 60) },
        { header: 'Description', render: (dashboard) => truncate(stringify(dashboard.description), 80) },
    ])
}

function getPathValue(item: JsonRecord, path: string): unknown {
    let value: unknown = item

    for (const part of path.split('.')) {
        if (!isRecord(value)) {
            return undefined
        }

        value = value[part]
    }

    return value
}

function getFirstValue(item: JsonRecord, keys: string[]): unknown {
    for (const key of keys) {
        const value = getPathValue(item, key)
        if (value !== null && value !== undefined && stringify(value) !== '') {
            return value
        }
    }

    return undefined
}

function hasAnyValue(items: JsonRecord[], keys: string[]): boolean {
    return items.some((item) => getFirstValue(item, keys) !== undefined)
}

function renderStatus(item: JsonRecord): string {
    if (typeof item.active === 'boolean') {
        return item.active ? chalk.green('active') : chalk.gray('inactive')
    }

    if (typeof item.enabled === 'boolean') {
        return item.enabled ? chalk.green('enabled') : chalk.gray('disabled')
    }

    if (typeof item.deleted === 'boolean' && item.deleted) {
        return chalk.red('deleted')
    }

    if (typeof item.archived === 'boolean' && item.archived) {
        return chalk.gray('archived')
    }

    return stringify(getFirstValue(item, ['status', 'state']))
}

function renderDate(item: JsonRecord, keys: string[]): string {
    return stringify(getFirstValue(item, keys))
        .replace('T', ' ')
        .replace(/\.\d+Z$/, 'Z')
}

function renderListValue(item: JsonRecord, keys: string[], maxLength: number): string {
    return truncate(stringify(getFirstValue(item, keys)), maxLength)
}

function printGenericList(result: unknown): void {
    const items = getListItems(result)
    const possibleColumns: Array<TableColumn & { keys: string[] }> = [
        {
            header: 'ID',
            keys: ['id', 'uuid', 'short_id'],
            render: (item) => renderListValue(item, ['id', 'uuid', 'short_id'], 24),
        },
        { header: 'Key', keys: ['key'], render: (item) => renderListValue(item, ['key'], 40) },
        {
            header: 'Name',
            keys: ['name', 'title', 'email'],
            render: (item) => renderListValue(item, ['name', 'title', 'email'], 60),
        },
        {
            header: 'Status',
            keys: ['active', 'enabled', 'deleted', 'archived', 'status', 'state'],
            render: renderStatus,
        },
        {
            header: 'Type',
            keys: ['type', 'kind', 'category', 'resource_type'],
            render: (item) => renderListValue(item, ['type', 'kind', 'category', 'resource_type'], 30),
        },
        {
            header: 'Created',
            keys: ['created_at', 'createdAt', 'created'],
            render: (item) => renderDate(item, ['created_at', 'createdAt', 'created']),
        },
        {
            header: 'Description',
            keys: ['description', 'summary'],
            render: (item) => renderListValue(item, ['description', 'summary'], 80),
        },
    ]
    const columns = possibleColumns.filter((column) => hasAnyValue(items, column.keys)).slice(0, 6)

    if (columns.length === 0) {
        printPrettyJson(result)
        return
    }

    printListTable(result, 'No results found.', columns)
}

function isListResult(result: unknown): boolean {
    return Array.isArray(result) || (isRecord(result) && Array.isArray(result.results))
}

function isEmptyResult(result: unknown): boolean {
    return result === null || result === undefined || (isRecord(result) && Object.keys(result).length === 0)
}

function summarizeObject(value: JsonRecord): string {
    const summary = getFirstValue(value, ['name', 'key', 'title', 'email', 'id', 'uuid'])

    if (summary !== undefined) {
        return stringify(summary)
    }

    return `${Object.keys(value).length} fields`
}

function formatDetailValue(value: unknown): string {
    if (Array.isArray(value)) {
        return `${value.length} item${value.length === 1 ? '' : 's'}`
    }

    if (isRecord(value)) {
        return summarizeObject(value)
    }

    return stringify(value)
}

function printObjectSummary(result: JsonRecord): void {
    const preferredKeys = [
        'id',
        'uuid',
        'short_id',
        'key',
        'name',
        'title',
        'email',
        'active',
        'enabled',
        'status',
        'state',
        'type',
        'kind',
        'description',
        'created_at',
        'updated_at',
    ]
    const remainingKeys = Object.keys(result)
        .filter((key) => !preferredKeys.includes(key))
        .sort()
    const keys = [...preferredKeys.filter((key) => key in result), ...remainingKeys].slice(0, 24)
    const table = new Table({ head: ['Field', 'Value'], wordWrap: true, wrapOnWordBoundary: false })

    for (const key of keys) {
        table.push([key, truncate(formatDetailValue(result[key]), 100)])
    }

    console.log(table.toString())

    if (Object.keys(result).length > keys.length) {
        console.log(
            chalk.gray(`Showing ${keys.length} of ${Object.keys(result).length} fields. Use --json for full output.`)
        )
    }
}

type ListFormatter = {
    matches: Array<string | RegExp>
    emptyMessage: string
    columns: TableColumn[]
}

function valueColumn(header: string, keys: string[], maxLength = 60): TableColumn {
    return { header, render: (item) => renderListValue(item, keys, maxLength) }
}

function dateColumn(header: string, keys: string[]): TableColumn {
    return { header, render: (item) => renderDate(item, keys) }
}

function statusColumn(): TableColumn {
    return { header: 'Status', render: renderStatus }
}

function countColumn(header: string, keys: string[]): TableColumn {
    return {
        header,
        render: (item) => {
            const value = getFirstValue(item, keys)
            return Array.isArray(value) ? stringify(value.length) : stringify(value)
        },
    }
}

function matchesToolName(toolName: string, patterns: Array<string | RegExp>): boolean {
    return patterns.some((pattern) => (typeof pattern === 'string' ? toolName === pattern : pattern.test(toolName)))
}

const listFormatters: ListFormatter[] = [
    {
        matches: ['actions-get-all'],
        emptyMessage: 'No actions found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            valueColumn('Type', ['type', 'steps.0.type'], 24),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: ['alerts-list', 'logs-alerts-list'],
        emptyMessage: 'No alerts found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            statusColumn(),
            valueColumn('Insight', ['insight', 'insight.name'], 40),
        ],
    },
    {
        matches: ['annotations-list'],
        emptyMessage: 'No annotations found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Content', ['content', 'description'], 80),
            dateColumn('Date', ['date_marker', 'created_at']),
            valueColumn('Scope', ['scope'], 20),
        ],
    },
    {
        matches: [/activity-logs?-list/, 'activity-log-list'],
        emptyMessage: 'No activity found.',
        columns: [
            dateColumn('Time', ['created_at', 'timestamp']),
            valueColumn('User', ['user.email', 'user.name', 'created_by.email'], 40),
            valueColumn('Activity', ['activity', 'event', 'action'], 40),
            valueColumn('Item', ['item_id', 'detail.name', 'scope'], 40),
        ],
    },
    {
        matches: [/approval-polic.*-list/, /change-requests-list/],
        emptyMessage: 'No approval items found.',
        columns: [
            valueColumn('ID', ['id', 'uuid'], 24),
            valueColumn('Name', ['name', 'title'], 60),
            statusColumn(),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/comments-list/],
        emptyMessage: 'No comments found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Author', ['user.email', 'created_by.email'], 40),
            valueColumn('Comment', ['content', 'body', 'text'], 80),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/org-members-list/, /role-members-list/, /persons-list/],
        emptyMessage: 'No people found.',
        columns: [
            valueColumn('ID', ['id', 'uuid', 'distinct_id'], 24),
            valueColumn('Name', ['name', 'first_name', 'properties.name'], 40),
            valueColumn('Email', ['email', 'properties.email'], 50),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/organizations-list/, /roles-list/],
        emptyMessage: 'No organizations or roles found.',
        columns: [
            valueColumn('ID', ['id', 'uuid'], 24),
            valueColumn('Name', ['name'], 60),
            valueColumn('Type', ['type', 'role_type'], 30),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/apm-.*-list/, /logs-attributes-list/, /logs-attribute-values-list/],
        emptyMessage: 'No attributes found.',
        columns: [
            valueColumn('Name', ['name', 'key', 'attribute', 'value'], 80),
            valueColumn('Type', ['type', 'kind'], 24),
            countColumn('Count', ['count', 'usage_count']),
        ],
    },
    {
        matches: [/batch-exports-list/],
        emptyMessage: 'No batch exports found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            valueColumn('Destination', ['destination.type', 'destination'], 40),
            statusColumn(),
        ],
    },
    {
        matches: [/cdp-function.*-list/, /hog-flows.*-list/, /workflows-list/],
        emptyMessage: 'No functions or workflows found.',
        columns: [
            valueColumn('ID', ['id', 'uuid'], 24),
            valueColumn('Name', ['name'], 60),
            statusColumn(),
            valueColumn('Type', ['type', 'kind', 'template_id'], 36),
        ],
    },
    {
        matches: [/cohorts-list/],
        emptyMessage: 'No cohorts found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            countColumn('Persons', ['count', 'people_count']),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/conversations-tickets-list/],
        emptyMessage: 'No tickets found.',
        columns: [
            valueColumn('ID', ['id', 'uuid'], 24),
            valueColumn('Title', ['title', 'subject'], 60),
            statusColumn(),
            dateColumn('Updated', ['updated_at']),
        ],
    },
    {
        matches: [/scheduled-changes-list/],
        emptyMessage: 'No scheduled changes found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Resource', ['resource_id', 'feature_flag.key', 'key'], 40),
            statusColumn(),
            dateColumn('Scheduled', ['scheduled_at', 'created_at']),
        ],
    },
    {
        matches: [/external-data-sources-list/],
        emptyMessage: 'No data warehouse sources found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Prefix', ['prefix', 'name'], 40),
            valueColumn('Source', ['source_type', 'type'], 30),
            statusColumn(),
        ],
    },
    {
        matches: [/external-data-schemas-list/],
        emptyMessage: 'No data warehouse schemas found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Table', ['name', 'table', 'schema_name'], 50),
            valueColumn('Sync type', ['sync_type'], 24),
            statusColumn(),
        ],
    },
    {
        matches: [/view-list/, /endpoints-get-all/],
        emptyMessage: 'No saved queries or endpoints found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            valueColumn('Type', ['type', 'kind'], 30),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/early-access-feature-list/],
        emptyMessage: 'No early access features found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            valueColumn('Stage', ['stage'], 24),
            statusColumn(),
        ],
    },
    {
        matches: [/error-tracking.*rules-list/, /error-tracking-symbol-sets-list/, /query-error-tracking-issues-list/],
        emptyMessage: 'No error tracking items found.',
        columns: [
            valueColumn('ID', ['id', 'fingerprint'], 24),
            valueColumn('Name', ['name', 'exception_type', 'description'], 60),
            statusColumn(),
            dateColumn('Last seen', ['last_seen', 'last_seen_at', 'updated_at']),
        ],
    },
    {
        matches: [/llma-.*-list/, /evaluations-get/, /evaluation.*-get-all/],
        emptyMessage: 'No LLM analytics items found.',
        columns: [
            valueColumn('ID', ['id', 'uuid'], 24),
            valueColumn('Name', ['name', 'title'], 60),
            valueColumn('Type', ['type', 'kind', 'provider'], 30),
            statusColumn(),
        ],
    },
    {
        matches: [/query-llm-traces-list/],
        emptyMessage: 'No LLM traces found.',
        columns: [
            valueColumn('Trace', ['trace_id', 'id'], 40),
            valueColumn('Input', ['input', 'name', 'prompt'], 60),
            valueColumn('Model', ['model', 'model_name'], 30),
            dateColumn('Created', ['created_at', 'timestamp']),
        ],
    },
    {
        matches: [/event-definitions-list/],
        emptyMessage: 'No event definitions found.',
        columns: [
            valueColumn('Name', ['name', 'event'], 60),
            valueColumn('Volume', ['volume_30_day', 'query_usage_30_day'], 24),
            statusColumn(),
            dateColumn('Last seen', ['last_seen_at', 'last_seen']),
        ],
    },
    {
        matches: [/properties-list/, /property-definitions/],
        emptyMessage: 'No properties found.',
        columns: [
            valueColumn('Name', ['name', 'property'], 60),
            valueColumn('Type', ['property_type', 'type'], 24),
            valueColumn('Group', ['group_type_index', 'group'], 20),
            dateColumn('Last seen', ['last_seen_at', 'last_seen']),
        ],
    },
    {
        matches: [/experiment-(get-all|list)/],
        emptyMessage: 'No experiments found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            statusColumn(),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/integrations-list/],
        emptyMessage: 'No integrations found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Kind', ['kind', 'integration'], 30),
            valueColumn('Display name', ['display_name', 'name'], 50),
            statusColumn(),
        ],
    },
    {
        matches: [/logs-alerts-events-list/],
        emptyMessage: 'No alert events found.',
        columns: [
            dateColumn('Time', ['timestamp', 'created_at']),
            valueColumn('Alert', ['alert.name', 'alert_id'], 40),
            valueColumn('Level', ['level', 'severity'], 20),
            valueColumn('Message', ['message', 'body'], 80),
        ],
    },
    {
        matches: [/notebooks-list/],
        emptyMessage: 'No notebooks found.',
        columns: [
            valueColumn('ID', ['short_id', 'id'], 16),
            valueColumn('Title', ['title', 'name'], 60),
            valueColumn('Created by', ['created_by.email'], 40),
            dateColumn('Updated', ['updated_at']),
        ],
    },
    {
        matches: [/inbox-reports-list/, /inbox-source-configs-list/],
        emptyMessage: 'No signal items found.',
        columns: [
            valueColumn('ID', ['id', 'uuid'], 24),
            valueColumn('Name', ['name', 'title'], 60),
            valueColumn('Type', ['type', 'kind', 'source_type'], 30),
            statusColumn(),
        ],
    },
    {
        matches: [/subscriptions.*-list/],
        emptyMessage: 'No subscriptions found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Target', ['target_type', 'insight.name', 'dashboard.name'], 40),
            valueColumn('Frequency', ['frequency', 'interval'], 24),
            statusColumn(),
        ],
    },
    {
        matches: [/proxy-list/],
        emptyMessage: 'No reverse proxies found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Domain', ['domain', 'target_cname'], 50),
            statusColumn(),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/session-recording.*list/, /query-session-recordings-list/],
        emptyMessage: 'No session recordings found.',
        columns: [
            valueColumn('ID', ['id', 'session_id'], 40),
            valueColumn('Person', ['person.email', 'person.name', 'distinct_id'], 50),
            valueColumn('Duration', ['duration'], 20),
            dateColumn('Started', ['start_time', 'created_at']),
        ],
    },
    {
        matches: [/surveys-get-all/],
        emptyMessage: 'No surveys found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            statusColumn(),
            countColumn('Responses', ['responses_count', 'response_count']),
        ],
    },
    {
        matches: [/usage-metrics-list/],
        emptyMessage: 'No usage metrics found.',
        columns: [
            valueColumn('ID', ['id'], 16),
            valueColumn('Name', ['name'], 60),
            valueColumn('Event', ['event_name', 'event'], 40),
            statusColumn(),
        ],
    },
    {
        matches: [/visual-review.*list/],
        emptyMessage: 'No visual review items found.',
        columns: [
            valueColumn('ID', ['id', 'uuid'], 24),
            valueColumn('Name', ['name', 'branch', 'snapshot_name'], 60),
            statusColumn(),
            dateColumn('Created', ['created_at']),
        ],
    },
    {
        matches: [/docs-search/, /entity-search/, /read-data-schema/, /read-data-warehouse-schema/],
        emptyMessage: 'No search results found.',
        columns: [
            valueColumn('Name', ['name', 'title', 'table', 'event'], 60),
            valueColumn('Type', ['type', 'kind', 'category'], 30),
            valueColumn('Description', ['description', 'summary'], 80),
        ],
    },
]

function printKnownList(toolName: string, result: unknown): boolean {
    if (toolName === 'feature-flag-get-all' || toolName === 'feature-flags-list') {
        printFeatureFlags(result)
        return true
    }

    if (toolName === 'insight-get-all' || toolName === 'insights-list') {
        printInsights(result)
        return true
    }

    if (toolName === 'dashboard-get-all' || toolName === 'dashboards-get-all' || toolName === 'dashboards-list') {
        printDashboards(result)
        return true
    }

    const formatter = listFormatters.find((candidate) => matchesToolName(toolName, candidate.matches))
    if (!formatter) {
        return false
    }

    printListTable(result, formatter.emptyMessage, formatter.columns)
    return true
}

function hexToTerminalColor(hex: string): { ansi: string; fn: (text: string) => string } {
    return { ansi: hexToAnsi(hex), fn: chalk.hex(hex) }
}

function getPostHogColor(index: number): {
    hex: string
    terminal: { ansi: string; fn: (text: string) => string }
    chartscii: string
} {
    const hex = getPostHogHex(index)
    return { hex, terminal: hexToTerminalColor(hex), chartscii: hex }
}

function getChartColors(asciichart: AsciiChart): Array<{ ansi: string; fn: (text: string) => string }> {
    return [
        { ansi: asciichart.blue, fn: chalk.blue },
        { ansi: asciichart.green, fn: chalk.green },
        { ansi: asciichart.yellow, fn: chalk.yellow },
        { ansi: asciichart.magenta, fn: chalk.magenta },
        { ansi: asciichart.cyan, fn: chalk.cyan },
        { ansi: asciichart.red, fn: chalk.red },
    ]
}

function plotBarChart(series: ChartSeries[]): void {
    const Chartscii = getChartscii()
    if (!Chartscii) {
        console.log(chalk.gray('Bar chart rendering is unavailable because chartscii is not installed.'))
        return
    }
    
    if (series.length === 0) {
        console.log(chalk.gray('Not enough data to plot.'))
        return
    }
    
    const termWidth = Math.max(60, Math.min(process.stdout.columns ?? 120, 200))
    
    series.forEach((s, seriesIndex) => {
        const data = s.data.map((v) => Number(v) || 0)
        const labels = s.labels.map((l) => stringify(l))
        
        // Use PostHog's color system for each data point/category
        const categoryColors = data.map((_, categoryIndex) => {
            return getPostHogColor(categoryIndex)
        })
        
        if (data.length === 0) return
        
        const action = isRecord(s.action) ? s.action : null
        const name = stringify(s.label) || (action ? stringify(action.name) : '') || `Series ${seriesIndex + 1}`
        const total = typeof s.count === 'number' ? chalk.gray(`  total: ${s.count}`) : ''
        
        // Use the first category's color for the series header
        const seriesColor = categoryColors[0]?.terminal || { fn: chalk.white }
        console.log(`${seriesColor.fn('●')} ${name}${total}`)
        console.log('')
        
        try {
            // Create individual colored charts for each bar
            const maxValue = Math.max(...data)

            // Find the width needed for all value labels
            const valueLabels = data.map(v => formatYValue(v))
            const maxLabelWidth = Math.max(...valueLabels.map(label => label.length))

            // Reserve room for the value label gutter (maxLabelWidth + ` ╢` separator).
            // No inner cap — the terminal width is already clamped above.
            const chartWidth = Math.max(20, termWidth - (maxLabelWidth + 3))
            
            data.forEach((value, index) => {
                if (value === 0) return
                
                const color = categoryColors[index]
                const label = labels[index]
                const normalizedData = [value] // Single value for this bar
                
                try {
                    const miniChart = new Chartscii(normalizedData, {
                        width: Math.floor((value / maxValue) * chartWidth),
                        height: 2,
                        naked: true,
                        color: color.chartscii
                    })
                    
                    // Extract just the bar part (without numbers) from chartscii output
                    const fullOutput = miniChart.create()
                    const lines = fullOutput.split('\n').filter(line => line.trim() !== '')
                    // Get the first line and split by space to separate number from bar
                    const firstLine = lines[0] || ''
                    const parts = firstLine.split(' ')
                    // Skip the first part (the number) and join the rest (the bar)
                    const barPart = parts.slice(1).join(' ')
                    const valueStr = formatYValue(value).padEnd(maxLabelWidth, ' ')
                    
                    console.log(`${valueStr} ╢${barPart}`)
                } catch (error) {
                    // Fallback to simple text display
                    const barLength = Math.floor((value / maxValue) * chartWidth)
                    const bar = '█'.repeat(Math.max(1, barLength))
                    const valueStr = formatYValue(value).padEnd(maxLabelWidth, ' ')
                    console.log(`${valueStr} ╢${color.terminal.fn(bar)}`)
                }
            })
            
            // Add spacing and labels
            console.log('')
            labels.forEach((label, i) => {
                if (data[i] === 0) return
                const value = data[i]
                const categoryColor = categoryColors[i]
                // Show full unrounded numbers in the legend
                console.log(`  ${categoryColor.terminal.fn('●')} ${label}: ${value}`)
            })
        } catch (error) {
            console.log(chalk.gray(`Failed to render bar chart: ${error instanceof Error ? error.message : 'Unknown error'}`))
        }
        
        if (seriesIndex < series.length - 1) {
            console.log('')
        }
    })
}

function plotTrendsSeries(series: ChartSeries[]): void {
    const asciichart = getAsciichart()
    if (!asciichart) {
        console.log(chalk.gray('Chart rendering is unavailable because asciichart is not installed.'))
        return
    }

    if (series.length === 0) {
        console.log(chalk.gray('Not enough data points to plot.'))
        return
    }
    // Series may report different data lengths if any are sparse or partially
    // filtered. Truncate everything to the shortest so asciichart receives a
    // rectangular multi-series array and labels stay aligned with chart cells.
    const points = Math.min(...series.map((s) => s.data.length))
    if (points < 2) {
        console.log(chalk.gray('Not enough data points to plot.'))
        return
    }

    const termWidth = Math.max(60, Math.min(process.stdout.columns ?? 120, 240))

    // Truncate every series to the same length, then downsample if there are
    // more points than horizontal cells — without this, hourly 720-point series
    // render at 720 columns wide and overflow the terminal.
    const maxPoints = maxRenderablePoints(termWidth)
    const truncated = series.map((s) => s.data.slice(0, points).map((v) => Number(v) || 0))
    const downsampled = truncated.map((data) => bucketAverage(data, maxPoints))
    const renderedPoints = downsampled[0].length
    const renderedLabels = bucketLabels(series[0].labels.slice(0, points), maxPoints)

    const step = pickStep(renderedPoints, termWidth)
    const numericSeries = downsampled.map((data) => widenSeries(data, step))

    // Replicate the web app's getTrendDatasetPosition: prefer the explicit
    // seriesIndex/colorIndex carried on the series, otherwise fall back to the
    // dataset position so each series keeps a stable slot in the 15-color palette.
    const seriesColors = series.map((s, i) => {
        const datasetPosition = (s as any).seriesIndex ?? (s as any).colorIndex ?? i
        return hexToTerminalColor(getPostHogHex(datasetPosition))
    })

    const chart = asciichart.plot(numericSeries.length === 1 ? numericSeries[0] : numericSeries, {
        height: 12,
        colors: seriesColors.map(c => c.ansi),
        format: (x: number) => formatYValue(x).padStart(5, ' '),
    })

    console.log(chart)
    console.log(buildLabelRow(renderedLabels, step))
    console.log('')

    series.forEach((s, i) => {
        const { fn: color } = seriesColors[i]
        const action = isRecord(s.action) ? s.action : null
        const name = friendlyBreakdownLabel(s.label) || (action ? stringify(action.name) : '') || `Series ${i + 1}`
        const total = typeof s.count === 'number' ? chalk.gray(`  total: ${s.count}`) : ''
        console.log(`  ${color('●')} ${name}${total}`)
    })
}

function printInsightDetail(result: unknown): void {
    if (!isRecord(result)) {
        printPrettyJson(result)
        return
    }

    const name = stringify(result.name) || stringify(result.derived_name) || '(untitled insight)'
    const description = stringify(result.description)

    console.log('')
    console.log(chalk.bold(name))
    if (description) {
        console.log(chalk.gray(description))
    }
    const meta: string[] = []
    if (result.id !== undefined) {
        meta.push(`id: ${stringify(result.id)}`)
    }
    if (result.short_id) {
        meta.push(`short_id: ${stringify(result.short_id)}`)
    }
    meta.push(`type: ${getInsightType(result)}`)
    if (isRecord(result.resolved_date_range)) {
        const from = stringify(result.resolved_date_range.date_from).slice(0, 10)
        const to = stringify(result.resolved_date_range.date_to).slice(0, 10)
        if (from && to) {
            meta.push(`range: ${from} → ${to}`)
        }
    }
    console.log(chalk.gray(meta.join('  ·  ')))
    console.log('')

    // Check if this is a bar chart data structure
    if (isBarChartData(result)) {
        const barChartSeries = convertToBarChartSeries(result)
        if (barChartSeries.length > 0) {
            plotBarChart(barChartSeries)
            console.log('')
            return
        }
    }

    // Fallback to regular trends chart logic
    const seriesData = Array.isArray(result.result) ? result.result : []
    const plottable = seriesData.filter(isChartSeries)

    if (plottable.length > 0) {
        if (shouldUseBarChart(plottable)) {
            plotBarChart(plottable)
        } else {
            plotTrendsSeries(plottable)
        }
        console.log('')
        return
    }

    if (printFunnelSteps(seriesData)) {
        return
    }

    console.log(chalk.gray('No chartable data for this insight type. Run with --json for the raw response.'))
}

interface FunnelStep {
    name?: unknown
    custom_name?: unknown
    order?: unknown
    count?: unknown
    breakdown_value?: unknown
    average_conversion_time?: unknown
}

function isFunnelStep(value: unknown): value is FunnelStep {
    return isRecord(value) && typeof value.count === 'number' && (typeof value.order === 'number' || 'name' in value)
}

function isFunnelBreakdown(value: unknown): value is FunnelStep[] {
    return Array.isArray(value) && value.length > 0 && value.every(isFunnelStep)
}

function formatBreakdownValue(value: unknown): string {
    if (Array.isArray(value)) return value.map((v) => stringify(v)).join(' / ')
    return stringify(value)
}

function printFunnelSteps(result: unknown[]): boolean {
    // Funnel results come back as either a flat list of steps or a list of
    // breakdown buckets, each itself a list of steps. Normalize to breakdowns.
    // Note the explicit length checks: `[].every(...)` returns true vacuously,
    // so without them an empty result would pass the breakdown check and crash
    // on `breakdowns[0]` below.
    if (result.length === 0) {
        return false
    }
    let breakdowns: FunnelStep[][]
    if (result.every(isFunnelStep)) {
        breakdowns = [result as FunnelStep[]]
    } else if (result.every(isFunnelBreakdown)) {
        breakdowns = result as FunnelStep[][]
    } else {
        return false
    }

    const stepHeaders = breakdowns[0].map(
        (step) => stringify(step.custom_name) || stringify(step.name) || `Step ${stringify(step.order)}`
    )

    const head = breakdowns.length > 1 ? ['Breakdown', ...stepHeaders] : stepHeaders
    const table = new Table({ head, wordWrap: true })

    for (const breakdown of breakdowns) {
        const firstCount = Number(breakdown[0]?.count ?? 0)
        const cells = breakdown.map((step) => {
            const count = Number(step.count ?? 0)
            const pct = firstCount > 0 ? ((count / firstCount) * 100).toFixed(1) : '0.0'
            return `${count.toLocaleString()}  ${chalk.gray(`(${pct}%)`)}`
        })
        if (breakdowns.length > 1) {
            const label = formatBreakdownValue(breakdown[0]?.breakdown_value) || '—'
            table.push([label, ...cells])
        } else {
            table.push(cells)
        }
    }

    console.log(table.toString())
    console.log('')
    return true
}

function printHumanResult(toolName: string, result: unknown): void {
    if (isEmptyResult(result)) {
        console.log(chalk.green('Done.'))
        return
    }

    if (CHARTABLE_INSIGHT_TOOLS.has(toolName)) {
        printInsightDetail(result)
        return
    }

    if (isListResult(result)) {
        if (printKnownList(toolName, result)) {
            return
        }

        printGenericList(result)
        return
    }

    if (isRecord(result)) {
        printObjectSummary(result)
        return
    }

    printPrettyJson(result)
}

export async function applyJqFilter(filter: string, result: unknown): Promise<string> {
    const output = await runJq(filter, result as Parameters<typeof runJq>[1], {
        input: 'json',
        output: 'pretty',
    })
    return typeof output === 'string' ? output : JSON.stringify(output ?? null, null, 2)
}

export async function printResult(argv: unknown, toolName: string, result: unknown): Promise<void> {
    if (isRecord(argv) && argv.json === true) {
        if (typeof argv.jq === 'string' && argv.jq.length > 0) {
            try {
                const filtered = await applyJqFilter(argv.jq, result)
                printHighlightedJson(filtered)
            } catch (error) {
                console.error(chalk.red('jq error:'), (error as Error).message)
                process.exit(1)
            }
            return
        }
        printPrettyJson(result)
        return
    }

    printHumanResult(toolName, result)
}
