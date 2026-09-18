import { z } from 'zod'

import { dashboardsList, dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import { featureFlagsList, featureFlagsRetrieve } from 'products/feature_flags/frontend/generated/api'
import {
    mcpServerInstallationsAvailableToolsRetrieve,
    mcpServerInstallationsCallToolCreate,
} from 'products/mcp_store/frontend/generated/api'
import {
    notebooksCreate,
    notebooksDestroy,
    notebooksList,
    notebooksPartialUpdate,
    notebooksRetrieve,
} from 'products/notebooks/frontend/generated/api'
import { NotebooksPartialUpdateBody } from 'products/notebooks/frontend/generated/api.zod'
import { insightsList, insightsRetrieve } from 'products/product_analytics/frontend/generated/api'

import { PosthogFilesystem, terminalFilename } from './posthogFilesystem'
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
        const shortId = z.object({ short_id: z.string().min(1) }).strict()
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
                    await notebooksDestroy(projectId, short_id, options)
                    return { deleted: short_id }
                },
                { readOnly: false, reference: notebook }
            ),
            command(
                'notebooks-partial-update',
                'Update a notebook. Include version when changing its contents.',
                NotebooksPartialUpdateBody.extend(shortId.shape).strict(),
                ({ short_id, ...body }) => notebooksPartialUpdate(projectId, short_id, body, options),
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
                shortId,
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
                    readOnly: tool.annotations.readOnlyHint === true,
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
                const property = object(properties[name])
                if (!(name in properties)) {
                    throw new Error(`Unknown argument --${rawName}. Run ph help ${tool.name}.`)
                }
                const value =
                    equals >= 0
                        ? argument.slice(equals + 1)
                        : property.type === 'boolean' && (!argv[index + 1] || argv[index + 1].startsWith('--'))
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
            const property = object(properties[name])
            if (
                typeof value === 'string' &&
                ['number', 'integer', 'boolean', 'object', 'array'].includes(String(property.type))
            ) {
                try {
                    args[name] = JSON.parse(value)
                } catch {
                    throw new Error(`Invalid ${property.type} value for --${name}.`)
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
