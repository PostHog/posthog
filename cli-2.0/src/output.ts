import chalk from 'chalk'
import { highlight } from 'cli-highlight'
import Table from 'cli-table3'
import { createRequire } from 'node:module'

import {
    buildLabelRow,
    type ChartSeries,
    formatYValue,
    getInsightType,
    isChartSeries,
    isRecord,
    type JsonRecord,
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

const require = createRequire(import.meta.url)
let cachedAsciichart: AsciiChart | null | undefined

function getAsciichart(): AsciiChart | undefined {
    if (cachedAsciichart !== undefined) {
        return cachedAsciichart ?? undefined
    }

    try {
        const module = require('asciichart') as AsciiChart | { default: AsciiChart }
        cachedAsciichart = 'default' in module ? module.default : module
    } catch {
        cachedAsciichart = null
    }

    return cachedAsciichart ?? undefined
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

function printRawJson(result: unknown): void {
    console.log(JSON.stringify(result, null, 2))
}

function printPrettyJson(result: unknown): void {
    const json = JSON.stringify(result, null, 2)

    if (!process.stdout.isTTY) {
        console.log(json)
        return
    }

    console.log(highlight(json, { language: 'json', ignoreIllegals: true }))
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
        { header: 'Key', render: (flag) => stringify(flag.key) },
        { header: 'Name', render: (flag) => stringify(flag.name) },
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

// asciichart wants raw SGR strings on its `colors` config; chalk 5 doesn't
// expose `.open`, so we keep two parallel constants — one for asciichart, one
// for legend bullets. Same ordering in both.
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

    const termWidth = Math.max(60, Math.min(process.stdout.columns ?? 100, 200))
    const step = pickStep(points, termWidth)

    const numericSeries = series.map((s) =>
        widenSeries(
            s.data.slice(0, points).map((v) => Number(v) || 0),
            step
        )
    )

    const chartColors = getChartColors(asciichart)
    const chart = asciichart.plot(numericSeries.length === 1 ? numericSeries[0] : numericSeries, {
        height: 12,
        colors: numericSeries.map((_, i) => chartColors[i % chartColors.length].ansi),
        format: (x: number) => formatYValue(x).padStart(5, ' '),
    })

    console.log(chart)
    console.log(buildLabelRow(series[0].labels.slice(0, points), step))
    console.log('')

    series.forEach((s, i) => {
        const { fn: color } = chartColors[i % chartColors.length]
        const action = isRecord(s.action) ? s.action : null
        const name = stringify(s.label) || (action ? stringify(action.name) : '') || `Series ${i + 1}`
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

    const seriesData = Array.isArray(result.result) ? result.result : []
    const plottable = seriesData.filter(isChartSeries)

    if (plottable.length === 0) {
        console.log(chalk.gray('No trends-style result to plot — showing JSON:'))
        console.log('')
        printPrettyJson(result)
        return
    }

    plotTrendsSeries(plottable)
    console.log('')
}

function printHumanResult(toolName: string, result: unknown): void {
    if (isEmptyResult(result)) {
        console.log(chalk.green('Done.'))
        return
    }

    if (toolName === 'insight-get' || toolName === 'insights-get') {
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

export function printResult(argv: unknown, toolName: string, result: unknown): void {
    if (isRecord(argv) && argv.json === true) {
        printRawJson(result)
        return
    }

    printHumanResult(toolName, result)
}
