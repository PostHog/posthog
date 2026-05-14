#!/usr/bin/env tsx
/**
 * Generates schema/command-mappings-enhanced.json from the MCP tool catalog.
 *
 * Conventions:
 *  - Each tool's CLI group is determined by the file it lives in
 *    (services/mcp/src/tools/generated/<file>.ts → FILE_GROUPS), or by
 *    NON_GENERATED_GROUPS for hand-written tools that aren't in those files.
 *  - The subcommand name is derived from the tool name's structure:
 *      strip the resource alias prefix and the CRUD verb suffix; what
 *      remains is the *modifier*. If the modifier is empty, fall back to
 *      a gh-style verb mapping (get/retrieve → view, get-all/list → list,
 *      partial-update/update → update, destroy/delete → delete).
 *  - When the same modifier is used by multiple tools in the same group
 *    (a sub-resource with multiple CRUD operations, e.g. logs/alerts), the
 *    verb is appended: `alerts-list`, `alerts-create`, `alerts-view`.
 *  - Collisions are a hard error — add an entry to EXPLICIT_NAMES.
 */

import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const CLI_ROOT = path.resolve(__dirname, '..')
const MCP_ROOT = path.resolve(CLI_ROOT, '../services/mcp')
const TOOL_DEFINITIONS_FILE = path.resolve(MCP_ROOT, 'schema/tool-definitions-all.json')
const TOOL_INPUTS_FILE = path.resolve(MCP_ROOT, 'schema/tool-inputs.json')
const GENERATED_TOOLS_DIR = path.resolve(MCP_ROOT, 'src/tools/generated')
const OUTPUT_FILE = path.resolve(CLI_ROOT, 'schema/command-mappings-enhanced.json')

interface ToolDefinition {
    description: string
    category: string
    feature: string
    summary: string
    title: string
    required_scopes: string[]
}

interface ToolInfo {
    name: string
    humanName: string
    description: string
    category: string
    endpoint?: string
    method?: string
    inputs: unknown
    mcp_tool: string
}

interface FileGroup {
    /** Single group all tools in the file belong to. */
    group?: string
    /**
     * Per-tool-prefix grouping for heterogeneous files. Each entry is
     * `[tool-name-prefix-with-trailing-dash, group]`. Longest match wins.
     */
    prefixes?: Array<[string, string]>
}

const FILE_GROUPS: Record<string, FileGroup> = {
    'actions.ts': { group: 'actions' },
    'alerts.ts': { group: 'alerts' },
    'annotations.ts': { group: 'annotations' },
    'batch_exports.ts': { group: 'batch-exports' },
    'cdp_function_templates.ts': { group: 'hog-functions' },
    'cdp_functions.ts': { group: 'hog-functions' },
    'cohorts.ts': { group: 'cohorts' },
    'conversations.ts': { group: 'support' },
    'core.ts': {
        prefixes: [
            ['subscriptions-', 'subscriptions'],
            ['project-', 'projects'],
            ['user-', 'users'],
        ],
    },
    'customer_analytics.ts': { group: 'usage' },
    'dashboards.ts': { group: 'dashboards' },
    'data_warehouse.ts': { group: 'data-warehouse' },
    'docs.ts': { group: 'docs' },
    'early_access_features.ts': { group: 'early-access-features' },
    'endpoints.ts': { group: 'endpoints' },
    'error_tracking.ts': { group: 'error-tracking' },
    'experiments.ts': { group: 'experiments' },
    'feature_flags.ts': { group: 'feature-flags' },
    'integrations.ts': { group: 'integrations' },
    'llm_analytics.ts': { group: 'llm-analytics' },
    'logs.ts': { group: 'logs' },
    'notebooks.ts': { group: 'notebooks' },
    'persons.ts': { group: 'persons' },
    'platform_features.ts': {
        prefixes: [
            ['advanced-activity-logs-', 'activity-logs'],
            ['activity-log-', 'activity-logs'],
            ['approval-', 'approvals'],
            ['change-requests-', 'approvals'],
            ['change-request-', 'approvals'],
            ['comments-', 'comments'],
            ['comment-', 'comments'],
            ['organizations-', 'organizations'],
            ['organization-', 'organizations'],
            ['org-', 'organizations'],
            ['roles-', 'roles'],
            ['role-', 'roles'],
            ['user-home-settings-', 'users'],
        ],
    },
    'product_analytics.ts': { group: 'insights' },
    'proxy-records.ts': { group: 'proxy' },
    'query-wrappers.ts': {
        prefixes: [
            ['query-llm-traces-', 'llm-analytics'],
            ['query-llm-trace', 'llm-analytics'],
            ['query-', 'query'],
        ],
    },
    'replay.ts': { group: 'session-recordings' },
    'sdk_doctor.ts': { group: 'debug' },
    'signals.ts': { group: 'signals' },
    'surveys.ts': { group: 'surveys' },
    'tracing.ts': { group: 'apm' },
    'visual_review.ts': { group: 'visual-review' },
    'web_analytics.ts': { group: 'web-analytics' },
    'workflows.ts': { group: 'workflows' },
}

/** Hand-written tools that don't appear in any generated/*.ts file. */
const NON_GENERATED_GROUPS: Record<string, string> = {
    'agent-feedback': 'feedback',
    'debug-mcp-ui-apps': 'debug',
    'entity-search': 'debug',
    'evaluation-create': 'llm-analytics',
    'evaluation-delete': 'llm-analytics',
    'evaluation-get': 'llm-analytics',
    'evaluation-run': 'llm-analytics',
    'evaluation-test-hog': 'llm-analytics',
    'evaluation-update': 'llm-analytics',
    'evaluations-get': 'llm-analytics',
    'event-definition-update': 'events',
    'event-definitions-list': 'events',
    'execute-sql': 'sql',
    'experiment-get-all': 'experiments',
    'experiment-results-get': 'experiments',
    'external-data-sources-db-schema': 'data-warehouse',
    'external-data-sources-jobs': 'data-warehouse',
    'external-data-sync-logs': 'data-warehouse',
    'get-llm-total-costs-for-project': 'llm-analytics',
    'hogql-schema': 'sql',
    'insight-query': 'insights',
    'projects-get': 'projects',
    'properties-list': 'properties',
    'property-definitions': 'properties',
    'query-generate-hogql-from-question': 'sql',
    'query-run': 'sql',
    'query-validate': 'sql',
    'read-data-schema': 'data-warehouse',
    'read-data-warehouse-schema': 'data-warehouse',
    'session-recording-summarize': 'session-recordings',
    'switch-organization': 'organizations',
    'switch-project': 'projects',
}

/**
 * Resource aliases per group (longest first). Used to strip the resource
 * prefix from a tool name to reveal its modifier.
 */
const RESOURCE_ALIASES: Record<string, string[]> = {
    actions: ['actions', 'action'],
    'activity-logs': ['activity-logs', 'activity-log'],
    alerts: ['alerts', 'alert'],
    annotations: ['annotations', 'annotation'],
    apm: ['apm'],
    approvals: ['approvals', 'approval'],
    'batch-exports': ['batch-exports', 'batch-export'],
    cohorts: ['cohorts', 'cohort'],
    comments: ['comments', 'comment'],
    'data-warehouse': ['data-warehouse', 'external-data', 'read-data'],
    dashboards: ['dashboards', 'dashboard'],
    debug: ['debug', 'sdk-doctor'],
    docs: ['docs'],
    'early-access-features': ['early-access-features', 'early-access-feature', 'early-access'],
    endpoints: ['endpoints', 'endpoint'],
    'error-tracking': ['error-tracking'],
    events: ['events', 'event-definitions', 'event-definition', 'event'],
    experiments: ['experiments', 'experiment'],
    'feature-flags': ['feature-flags', 'feature-flag'],
    feedback: ['feedback', 'agent-feedback'],
    'hog-functions': ['hog-functions', 'hog-function', 'cdp-functions', 'cdp-function'],
    insights: ['insights', 'insight'],
    integrations: ['integrations', 'integration'],
    'llm-analytics': ['llm-analytics', 'llma', 'evaluations', 'evaluation', 'llm-traces', 'llm-trace'],
    logs: ['logs', 'log'],
    notebooks: ['notebooks', 'notebook'],
    organizations: ['organizations', 'organization', 'org'],
    persons: ['persons', 'person'],
    projects: ['projects', 'project'],
    properties: ['properties', 'property-definitions', 'property'],
    proxy: ['proxy'],
    query: ['query'],
    roles: ['roles', 'role'],
    'session-recordings': ['session-recordings', 'session-recording'],
    signals: ['signals', 'signal', 'inbox'],
    sql: ['sql', 'execute-sql', 'hogql-schema', 'query'],
    subscriptions: ['subscriptions', 'subscription'],
    support: ['support', 'conversations-tickets', 'conversations'],
    surveys: ['surveys', 'survey'],
    usage: ['usage', 'usage-metrics'],
    users: ['users', 'user'],
    'visual-review': ['visual-review'],
    'web-analytics': ['web-analytics'],
    workflows: ['workflows', 'workflow', 'hog-flows', 'hog-flow'],
}

const TRAILING_VERBS = [
    'partial-update',
    'get-definition',
    'get-all',
    'retrieve',
    'destroy',
    'create',
    'update',
    'delete',
    'list',
    'get',
]

const LEADING_VERBS = ['create', 'delete', 'update', 'get', 'add', 'remove', 'switch', 'query', 'read']

/** MCP CRUD verbs mapped to their gh-style CLI equivalents. */
const CLI_VERB: Record<string, string> = {
    get: 'view',
    retrieve: 'view',
    'get-definition': 'view',
    'get-all': 'list',
    list: 'list',
    create: 'create',
    update: 'update',
    'partial-update': 'update',
    delete: 'delete',
    destroy: 'delete',
    add: 'add',
    remove: 'remove',
    switch: 'switch',
    query: 'query',
    read: 'read',
}

/** Hand-picked subcommand names that the algorithm can't reasonably derive. */
const EXPLICIT_NAMES: Record<string, string> = {
    'agent-feedback': 'submit',
    'cohorts-add-persons-to-static-cohort-partial-update': 'add-persons',
    'cohorts-rm-person-from-static-cohort-partial-update': 'remove-persons',
    'dashboard-insights-run': 'run',
    'debug-mcp-ui-apps': 'mcp-ui-apps',
    'entity-search': 'search',
    'evaluations-get': 'list', // legacy alias for `llma-evaluation-list` style; this one returns a list
    'execute-sql': 'execute',
    'experiment-get-all': 'list-legacy', // duplicate of `experiment-list` from older MCP definitions
    'insights-all-activity-retrieve': 'recent-activity',
    'projects-get': 'list',
    'query-llm-trace': 'trace',
    'query-llm-traces-list': 'traces',
    'switch-organization': 'switch',
    'switch-project': 'switch',
}

interface ParsedTool {
    file?: string
    endpoint?: string
    method?: string
}

function parseGeneratedTools(): Record<string, ParsedTool> {
    const map: Record<string, ParsedTool> = {}
    if (!fs.existsSync(GENERATED_TOOLS_DIR)) return map

    for (const file of fs.readdirSync(GENERATED_TOOLS_DIR)) {
        if (!file.endsWith('.ts') || file === 'index.ts') continue
        const content = fs.readFileSync(path.join(GENERATED_TOOLS_DIR, file), 'utf8')

        // Match `name: 'tool-name', ... context.api.request({ method: 'X', path: `Y` })`
        const blockRegex =
            /name:\s*'([^']+)'[\s\S]*?context\.api\.request[^{]*\{[\s\S]*?method:\s*'([A-Z]+)'[\s\S]*?path:\s*`([^`]+)`/g
        let m: RegExpExecArray | null
        while ((m = blockRegex.exec(content)) !== null) {
            const [, name, method, rawPath] = m
            // Don't overwrite — keep the first occurrence per file (deterministic)
            if (!map[name]) {
                map[name] = { file, method, endpoint: cleanupEndpoint(rawPath) }
            }
        }

        // Also catch tools that didn't expose an api.request (e.g. wrappers)
        const nameOnly = /name:\s*'([^']+)'/g
        let nm: RegExpExecArray | null
        while ((nm = nameOnly.exec(content)) !== null) {
            if (!map[nm[1]]) {
                map[nm[1]] = { file }
            }
        }
    }
    return map
}

function cleanupEndpoint(rawPath: string): string {
    return rawPath
        .replace(/\$\{encodeURIComponent\(String\(projectId\)\)\}/g, '{project_id}')
        .replace(/\$\{encodeURIComponent\(String\(orgId\)\)\}/g, '{org_id}')
        .replace(/\$\{encodeURIComponent\(String\(params\.id\)\)\}/g, '{id}')
        .replace(/\$\{encodeURIComponent\(String\(params\.([^)]+)\)\)\}/g, (_, p) => `{${p}}`)
        .replace(/\$\{encodeURIComponent\(String\(([^)]+)\)\)\}/g, (_, v) => {
            const snake = String(v)
                .replace(/([A-Z])/g, '_$1')
                .toLowerCase()
            return `{${snake}}`
        })
}

function resolveGroup(toolName: string, parsed: ParsedTool | undefined): string | null {
    if (parsed?.file) {
        const fileGroup = FILE_GROUPS[parsed.file]
        if (fileGroup?.group) return fileGroup.group
        if (fileGroup?.prefixes) {
            const sorted = [...fileGroup.prefixes].sort((a, b) => b[0].length - a[0].length)
            for (const [prefix, group] of sorted) {
                if (toolName.startsWith(prefix) || toolName === prefix.replace(/-$/, '')) {
                    return group
                }
            }
        }
    }
    return NON_GENERATED_GROUPS[toolName] ?? null
}

interface DerivedName {
    modifier: string
    verb: string | null
}

function deriveModifierAndVerb(toolName: string, group: string): DerivedName {
    let working = toolName
    const aliases = [...(RESOURCE_ALIASES[group] ?? [])].sort((a, b) => b.length - a.length)
    let trailingVerb: string | null = null
    let leadingVerb: string | null = null

    // 1. Strip trailing verb (longest match wins)
    for (const v of TRAILING_VERBS) {
        if (working === v) {
            trailingVerb = v
            working = ''
            break
        }
        if (working.endsWith('-' + v)) {
            trailingVerb = v
            working = working.slice(0, -(v.length + 1))
            break
        }
    }

    // 2. Strip leading resource alias (longest first)
    for (const a of aliases) {
        if (working === a) {
            working = ''
            break
        }
        if (working.startsWith(a + '-')) {
            working = working.slice(a.length + 1)
            break
        }
    }

    // 3. Handle leading-verb shape (e.g. `create-feature-flag`, `read-data-schema`,
    //    `query-session-recordings-list`). Only strip the verb if what follows is
    //    (or contains) the resource alias — otherwise we'd mangle unrelated names.
    if (working) {
        for (const v of LEADING_VERBS) {
            if (working === v) {
                leadingVerb = v
                working = ''
                break
            }
            if (working.startsWith(v + '-')) {
                const rest = working.slice(v.length + 1)
                let stripped: string | null = null
                for (const a of aliases) {
                    if (rest === a) {
                        stripped = ''
                        break
                    }
                    if (rest.endsWith('-' + a)) {
                        stripped = rest.slice(0, -(a.length + 1))
                        break
                    }
                    if (rest.startsWith(a + '-')) {
                        stripped = rest.slice(a.length + 1)
                        break
                    }
                }
                if (stripped !== null) {
                    leadingVerb = v
                    working = stripped
                    break
                }
            }
        }
    }

    return { modifier: working, verb: trailingVerb ?? leadingVerb }
}

interface PendingTool {
    toolName: string
    toolDef: ToolDefinition
    group: string
    derived: DerivedName
    parsed: ParsedTool | undefined
}

function emitName(group: string, derived: DerivedName, modifierCounts: Record<string, Record<string, number>>): string {
    const { modifier, verb } = derived
    if (!modifier) {
        return verb ? (CLI_VERB[verb] ?? verb) : 'view'
    }
    const count = modifierCounts[group]?.[modifier] ?? 0
    if (count > 1 && verb) {
        return `${modifier}-${CLI_VERB[verb] ?? verb}`
    }
    return modifier
}

function inputSchemaKeyFor(toolName: string): string {
    const camel = toolName.charAt(0).toUpperCase() + toolName.slice(1).replace(/-([a-z])/g, (_, c) => c.toUpperCase())
    return `${camel}Schema`
}

async function generateEnhancedMapping(): Promise<void> {
    console.log('🔧 Extracting tool information from generated MCP tools...')

    const toolDefinitions = JSON.parse(fs.readFileSync(TOOL_DEFINITIONS_FILE, 'utf8')) as Record<string, ToolDefinition>
    const toolInputs = JSON.parse(fs.readFileSync(TOOL_INPUTS_FILE, 'utf8'))
    const parsedTools = parseGeneratedTools()

    // Pass 1: resolve group + (modifier, verb) for every tool
    const pending: PendingTool[] = []
    const ungrouped: string[] = []

    for (const [toolName, toolDef] of Object.entries(toolDefinitions)) {
        const parsed = parsedTools[toolName]
        const group = resolveGroup(toolName, parsed)
        if (!group) {
            ungrouped.push(toolName)
            continue
        }
        const derived = deriveModifierAndVerb(toolName, group)
        pending.push({ toolName, toolDef, group, derived, parsed })
    }

    if (ungrouped.length > 0) {
        console.error('\n❌ Tools could not be assigned to any group:')
        for (const t of ungrouped) console.error(`   - ${t}`)
        throw new Error(
            `${ungrouped.length} tool(s) without group. Add entries to FILE_GROUPS or NON_GENERATED_GROUPS.`
        )
    }

    // Pass 2: count modifier occurrences per group (to decide whether to suffix verb)
    const modifierCounts: Record<string, Record<string, number>> = {}
    for (const p of pending) {
        if (!p.derived.modifier) continue
        modifierCounts[p.group] ??= {}
        modifierCounts[p.group][p.derived.modifier] = (modifierCounts[p.group][p.derived.modifier] ?? 0) + 1
    }

    // Pass 3: emit final names + detect collisions
    const commands: Record<string, { description: string; subcommands: Record<string, ToolInfo> }> = {}
    const collisions: Record<string, Record<string, string[]>> = {}

    for (const p of pending) {
        const finalName = EXPLICIT_NAMES[p.toolName] ?? emitName(p.group, p.derived, modifierCounts)

        commands[p.group] ??= { description: `Manage ${p.group}`, subcommands: {} }

        if (commands[p.group].subcommands[finalName]) {
            collisions[p.group] ??= {}
            const existingTool = commands[p.group].subcommands[finalName].mcp_tool
            const list = collisions[p.group][finalName] ?? [existingTool]
            list.push(p.toolName)
            collisions[p.group][finalName] = list
            continue
        }

        const inputSchema = toolInputs.definitions?.[inputSchemaKeyFor(p.toolName)]
        commands[p.group].subcommands[finalName] = {
            name: finalName,
            humanName: finalName,
            description: p.toolDef.summary || (p.toolDef.description ?? '').split('.')[0] || p.toolDef.title,
            category: p.toolDef.category,
            endpoint: p.parsed?.endpoint,
            method: p.parsed?.method,
            inputs: inputSchema ?? {},
            mcp_tool: p.toolName,
        }
    }

    if (Object.keys(collisions).length > 0) {
        console.error('\n❌ Subcommand name collisions detected. Resolve via EXPLICIT_NAMES:')
        for (const [group, names] of Object.entries(collisions)) {
            for (const [name, tools] of Object.entries(names)) {
                console.error(`   ${group}/${name} ← ${tools.join(' AND ')}`)
            }
        }
        throw new Error('Name collisions — refusing to emit ambiguous mappings.')
    }

    const enhancedMapping = {
        version: '2.0',
        generated_at: new Date().toISOString(),
        commands,
        stats: {
            total_tools: Object.keys(toolDefinitions).length,
            mapped_tools: pending.length,
            commands_created: Object.keys(commands).length,
        },
    }

    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(enhancedMapping, null, 2))

    console.log(`✅ Generated enhanced command mappings`)
    console.log(`📊 Processed: ${pending.length}/${Object.keys(toolDefinitions).length} tools`)
    console.log(`🏗️  Created: ${Object.keys(commands).length} command groups`)
    console.log(`📄 Output: ${OUTPUT_FILE}`)
}

async function main(): Promise<void> {
    try {
        await generateEnhancedMapping()
        console.log('🎉 Enhanced mapping generation complete!')
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error)
        console.error('❌ Failed to generate enhanced mappings:', msg)
        process.exit(1)
    }
}

if (import.meta.url === `file://${process.argv[1]}`) {
    main()
}
