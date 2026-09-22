import { z } from 'zod'

import { dashboardsList, dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import { featureFlagsList, featureFlagsRetrieve } from 'products/feature_flags/frontend/generated/api'
import {
    mcpServerInstallationsAvailableToolsRetrieve,
    mcpServerInstallationsCallToolCreate,
} from 'products/mcp_store/frontend/generated/api'
import {
    notebooksCreate,
    notebooksList,
    notebooksPartialUpdate,
    notebooksRetrieve,
} from 'products/notebooks/frontend/generated/api'
import { NotebooksPartialUpdateBody } from 'products/notebooks/frontend/generated/api.zod'
import { insightsList, insightsRetrieve } from 'products/product_analytics/frontend/generated/api'

import { markdownNode, PosthogFilesystem, terminalFilename } from './posthogFilesystem'
import { TerminalCommands } from './terminalCommands'

interface Command {
    name: string
    description: string
    inputSchema: Record<string, unknown>
    readOnly: boolean
    reference?: { parameter: string; type: string }
    invoke: (args: Record<string, unknown>) => Promise<unknown>
}

const aliases: Record<string, string> = {
    'notebook-list': 'notebooks-list',
    'notebook-get': 'notebooks-retrieve',
    'notebook-create': 'notebooks-create-markdown',
    'notebook-update': 'notebooks-partial-update',
    'notebook-delete': 'notebooks-destroy',
}

const help = `ph: PostHog commands

ph tools [search]                 List project commands and connected MCP tools
ph help <command>                Show arguments and whether a command writes data
ph <command> [ID or file]         Run a command
ph <command> --key value         Set a named argument
ph <command> --json '{...}'       Supply a JSON arguments object
ph <command> --json @args.json    Read arguments from a Linux file
ph <command> --json -            Read arguments from stdin
ph refresh                       Reload the project tree and connected tool catalog

Examples:
  ph notebooks-list --limit 10 | jq .results
  ph notebook-get '/posthog/files/Research/Notes.md'
  ph notebook-create --title 'Notes' --markdown @/tmp/notes.md
  ph notebook-delete <short-id>
  ph help notebook-delete

An @file value reads its contents. Built-in IDs can be paths under /posthog/files
or /posthog/api. JSON results go to stdout; errors go to stderr with a nonzero exit.
Connected tools use server/tool names from ph tools and their existing MCP permissions.
The built-in commands cover notebooks and reading insights, dashboards, and feature flags.
Tool schemas are files under /posthog/tools. Run ph refresh after creating or deleting objects.
`

function command<T extends z.ZodType>(
    name: string,
    description: string,
    schema: T,
    invoke: (args: z.infer<T>) => Promise<unknown>,
    options: Pick<Command, 'readOnly' | 'reference'> = { readOnly: true }
): Command {
    return {
        name,
        description,
        inputSchema: z.toJSONSchema(schema),
        ...options,
        invoke: async (args) => invoke(schema.parse(args)),
    }
}

function object(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {}
}

// Notebook search reads text_content, and the API keeps the stored value when an update omits it,
// so a content change has to carry the matching text the way every other writer does.
function notebookUpdate<T extends { content?: unknown; text_content?: string | null }>(body: T): T {
    if (body.content === undefined || body.text_content !== undefined) {
        return body
    }
    const node = markdownNode(body.content)
    if (!node) {
        throw new Error('Include text_content when updating content that is not a markdown notebook.')
    }
    return { ...body, text_content: node.attrs.markdown }
}

const jsonTypes = ['number', 'integer', 'boolean', 'object', 'array']

// Connected MCP servers write their own schemas, so a property can state its type through a
// reference, a composed branch, or a type array instead of a plain `type`.
function schemaTypes(property: unknown, root: Record<string, unknown>, depth = 0): Set<string> {
    const types = new Set<string>()
    const node = object(property)
    if (depth > 8) {
        return types
    }
    const pointer = typeof node.$ref === 'string' ? /^#\/(\$defs|definitions)\/([^/]+)$/.exec(node.$ref) : null
    if (pointer) {
        const name = pointer[2].replaceAll('~1', '/').replaceAll('~0', '~')
        for (const type of schemaTypes(object(root[pointer[1]])[name], root, depth + 1)) {
            types.add(type)
        }
    }
    for (const type of Array.isArray(node.type) ? node.type : [node.type]) {
        if (typeof type === 'string' && type !== 'null') {
            types.add(type)
        }
    }
    for (const key of ['anyOf', 'oneOf', 'allOf']) {
        for (const branch of Array.isArray(node[key]) ? (node[key] as unknown[]) : []) {
            for (const type of schemaTypes(branch, root, depth + 1)) {
                types.add(type)
            }
        }
    }
    return types
}

export class PosthogCommands {
    private readonly commands = new Map<string, Command>()
    private readonly toolDirectory
    private connectedLoaded = false

    constructor(
        private projectId: string,
        private signal: AbortSignal,
        private filesystem: PosthogFilesystem
    ) {
        this.toolDirectory = filesystem.directory('tools', filesystem.root)
        const options = { signal }
        const pagination = z
            .object({
                limit: z.number().int().positive().optional(),
                offset: z.number().int().nonnegative().optional(),
            })
            .strict()
        const shortId = z
            .object({
                short_id: z
                    .string()
                    .regex(/^[\p{L}\p{N}]{1,12}(?![\s\S])/u, 'Use a notebook ID with up to 12 letters or numbers.'),
            })
            .strict()
        const insightId = z
            .object({
                short_id: z
                    .string()
                    .regex(/^(?:[A-Za-z0-9]{1,12}|[0-9]+)(?![\s\S])/, 'Use an insight short ID or numeric ID.'),
            })
            .strict()
        const id = z.object({ id: z.number().int().positive() }).strict()
        const notebook = { parameter: 'short_id', type: 'notebook' }
        const builtins = [
            command(
                'notebooks-list',
                'List notebooks in this project.',
                pagination.extend({ search: z.string().optional() }),
                (args) => notebooksList(projectId, args, options)
            ),
            command(
                'notebooks-retrieve',
                'Read a notebook by short ID or filesystem path.',
                shortId,
                ({ short_id }) => notebooksRetrieve(projectId, short_id, options),
                { readOnly: true, reference: notebook }
            ),
            command(
                'notebooks-destroy',
                'Delete a notebook from PostHog.',
                shortId,
                async ({ short_id }) => {
                    await notebooksPartialUpdate(projectId, short_id, { deleted: true }, options)
                    return { deleted: short_id }
                },
                { readOnly: false, reference: notebook }
            ),
            command(
                'notebooks-partial-update',
                'Update a notebook. Include version when changing its contents.',
                NotebooksPartialUpdateBody.extend(shortId.shape).strict(),
                ({ short_id, ...body }) => notebooksPartialUpdate(projectId, short_id, notebookUpdate(body), options),
                { readOnly: false, reference: notebook }
            ),
            command(
                'notebooks-create-markdown',
                'Create a markdown notebook. Its title becomes the first heading.',
                z.object({ title: z.string().min(1).max(256), markdown: z.string().optional() }).strict(),
                async ({ title, markdown }) => {
                    const text = `# ${title}${markdown?.trim() ? `\n\n${markdown.trim()}` : ''}`
                    return notebooksCreate(
                        projectId,
                        {
                            title,
                            content: {
                                type: 'doc',
                                content: [
                                    {
                                        type: 'ph-markdown-notebook',
                                        attrs: { nodeId: 'markdown-notebook-v2', markdown: text },
                                    },
                                ],
                            },
                            text_content: text,
                        },
                        options
                    )
                },
                { readOnly: false }
            ),
            command('insights-list', 'List insights in this project.', pagination, (args) =>
                insightsList(projectId, args, options)
            ),
            command(
                'insight-get',
                'Read an insight by short ID or filesystem path.',
                insightId,
                ({ short_id }) => insightsRetrieve(projectId, short_id, undefined, options),
                { readOnly: true, reference: { parameter: 'short_id', type: 'insight' } }
            ),
            command('dashboards-get-all', 'List dashboards in this project.', pagination, (args) =>
                dashboardsList(projectId, args, options)
            ),
            command(
                'dashboard-get',
                'Read a dashboard by ID or filesystem path.',
                id,
                ({ id }) => dashboardsRetrieve(projectId, id, undefined, options),
                { readOnly: true, reference: { parameter: 'id', type: 'dashboard' } }
            ),
            command('feature-flag-get-all', 'List feature flags in this project.', pagination, (args) =>
                featureFlagsList(projectId, args, options)
            ),
            command(
                'feature-flag-get-definition',
                'Read a feature flag by ID or filesystem path.',
                id,
                ({ id }) => featureFlagsRetrieve(projectId, id, options),
                { readOnly: true, reference: { parameter: 'id', type: 'feature_flag' } }
            ),
        ]
        for (const tool of builtins) {
            this.register(tool)
        }
        new TerminalCommands(filesystem, (argv, cwd) => this.execute(argv, cwd))
    }

    private register(tool: Command): void {
        this.commands.set(tool.name, tool)
        const { invoke: _, ...description } = tool
        this.filesystem.text(
            `${terminalFilename(tool.name)}.json`,
            this.toolDirectory,
            JSON.stringify(description, null, 2)
        )
    }

    private async loadConnected(): Promise<void> {
        if (this.connectedLoaded) {
            return
        }
        const { servers } = await mcpServerInstallationsAvailableToolsRetrieve(this.projectId, { signal: this.signal })
        for (const server of servers) {
            const namespace =
                servers.filter((candidate) => candidate.slug === server.slug).length > 1
                    ? `${server.slug}@${server.installation_id}`
                    : server.slug
            for (const tool of server.tools) {
                this.register({
                    name: `${namespace}/${tool.name}`,
                    description: `${tool.description}${tool.approval_state === 'needs_approval' ? '\nNeeds approval in Settings → MCP servers.' : ''}`,
                    inputSchema: tool.input_schema,
                    // Upstream MCP annotations are advisory, so readOnlyHint cannot prove that a
                    // connected tool only reads. Report every connected tool as a writer until the
                    // gateway returns its own classification.
                    readOnly: false,
                    invoke: async (args) => {
                        const result = await mcpServerInstallationsCallToolCreate(
                            this.projectId,
                            server.installation_id,
                            { tool_name: tool.name, arguments: args },
                            { signal: this.signal }
                        )
                        if (result.is_error) {
                            throw new Error(JSON.stringify(result.content))
                        }
                        return result.structured_content ?? result.content
                    },
                })
            }
        }
        this.connectedLoaded = true
    }

    private parseArguments(tool: Command, argv: string[], cwd: string): Record<string, unknown> {
        const args: Record<string, unknown> = Object.create(null)
        const properties = object(tool.inputSchema.properties)
        for (let index = 0; index < argv.length; index++) {
            const argument = argv[index]
            if (argument === '--json') {
                const value: unknown = JSON.parse(argv[++index] ?? '')
                if (!value || typeof value !== 'object' || Array.isArray(value)) {
                    throw new Error('--json requires a JSON object.')
                }
                Object.assign(args, value)
            } else if (argument.startsWith('--')) {
                const equals = argument.indexOf('=')
                const rawName = argument.slice(2, equals < 0 ? undefined : equals)
                const name = rawName in properties ? rawName : rawName.replaceAll('-', '_')
                if (!(name in properties)) {
                    throw new Error(`Unknown argument --${rawName}. Run ph help ${tool.name}.`)
                }
                const types = schemaTypes(properties[name], tool.inputSchema)
                const flag = types.size > 0 && [...types].every((type) => type === 'boolean')
                const value =
                    equals >= 0
                        ? argument.slice(equals + 1)
                        : flag && (!argv[index + 1] || argv[index + 1].startsWith('--'))
                          ? 'true'
                          : argv[++index]
                if (value === undefined) {
                    throw new Error(`Missing value for --${rawName}.`)
                }
                args[name] = value
            } else if (tool.reference && args[tool.reference.parameter] === undefined) {
                args[tool.reference.parameter] = argument
            } else {
                throw new Error(`Unexpected argument ${argument}. Run ph help ${tool.name}.`)
            }
        }
        if (tool.reference && typeof args[tool.reference.parameter] === 'string') {
            args[tool.reference.parameter] = this.filesystem.resolveReference(
                args[tool.reference.parameter] as string,
                cwd,
                tool.reference.type
            )
        }
        for (const [name, value] of Object.entries(args)) {
            const types = [...schemaTypes(properties[name], tool.inputSchema)]
            // A property that also accepts a string keeps the text it was given.
            if (typeof value === 'string' && types.length > 0 && types.every((type) => jsonTypes.includes(type))) {
                try {
                    args[name] = JSON.parse(value)
                } catch {
                    throw new Error(`Invalid ${types.join(' or ')} value for --${name}.`)
                }
            }
        }
        return args
    }

    async execute(argv: string[], cwd: string): Promise<unknown> {
        const [name = 'help', ...rest] = argv
        if (name === 'help' || name === '--help') {
            if (!rest.length) {
                return help
            }
            const tool = await this.find(rest[0])
            const { invoke: _, ...description } = tool
            return description
        }
        if (name === 'refresh') {
            await this.filesystem.load()
            this.connectedLoaded = false
            for (const key of this.commands.keys()) {
                if (key.includes('/')) {
                    this.commands.delete(key)
                    this.toolDirectory.children!.delete(`${terminalFilename(key)}.json`)
                }
            }
            await this.loadConnected()
            return 'Project files and connected tools refreshed.'
        }
        if (name === 'tools') {
            await this.loadConnected()
            const search = rest.join(' ').toLowerCase()
            return [...this.commands.values()]
                .filter((tool) => `${tool.name} ${tool.description}`.toLowerCase().includes(search))
                .map(({ name, description, readOnly }) => ({ name, description, readOnly }))
        }
        const tool = await this.find(name)
        if (rest.length === 1 && rest[0] === '--help') {
            const { invoke: _, ...description } = tool
            return description
        }
        return tool.invoke(this.parseArguments(tool, rest, cwd))
    }

    private async find(name: string): Promise<Command> {
        const canonical = aliases[name] ?? name
        if (!this.commands.has(canonical)) {
            await this.loadConnected()
        }
        const tool = this.commands.get(canonical)
        if (!tool) {
            throw new Error(`Unknown command ${name}. Run ph tools to find a command.`)
        }
        return tool
    }
}
