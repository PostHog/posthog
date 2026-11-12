import type { ParseError } from 'jsonc-parser'
import { basename, dirname, join, resolve } from 'node:path'
import { z } from 'zod'

import { knownAgent } from '@/core/agent'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import { JsonObject } from '@/core/json'
import { escapeControls } from '@/core/output'
import { isInside, realWritePath } from '@/core/paths'
import type { Env, Runtime } from '@/core/runtime'
import { regionOf, type RegionId } from '@/posthog/host'
import { chooseLogin } from '@/posthog/login/choose'
import { readSettings } from '@/posthog/settings'

import { codexServer, withCodexServer, type CodexServer } from './codex-toml'

// The clients the Wizard writes a config file for, with the same paths, formats and entries, so a
// server either tool added counts as added in the other.
export const MCP_AGENTS = ['claude-code', 'cursor', 'codex', 'vscode', 'zed', 'opencode', 'claude-desktop'] as const

export type McpAgent = (typeof MCP_AGENTS)[number]

export const SERVER_NAME = 'posthog'

// The same URL the Wizard writes for both regions.
const MCP_URLS: Record<RegionId, string> = {
    us: 'https://mcp.posthog.com/mcp',
    eu: 'https://mcp.posthog.com/mcp',
}

// By origin, so the Wizard's URLs with a path or query, like `?features=...`, count too. The EU host
// serves the same MCP server, so an entry another tool wrote for it is PostHog's as well.
const POSTHOG_ORIGINS = new Set([
    ...Object.values(MCP_URLS).map((url) => new URL(url).origin),
    'https://mcp-eu.posthog.com',
])

export interface Where {
    runtime: Runtime
    home: string
    root: string
}

export interface McpFile {
    path: string
    // A project file comes with the repository, so a write to it must stay inside the repository.
    scope: 'project' | 'user'
}

interface JsonFormat {
    kind: 'json'
    serversKey: string
    entry(url: string): Record<string, unknown>
}

interface JsonLocation {
    path: string
    keys: readonly string[]
}

interface McpClient {
    name: string
    file(where: Where): Promise<McpFile> | McpFile
    format: JsonFormat | { kind: 'codex-toml' }
    elsewhere?(where: Where): JsonLocation[]
    afterAdd: string
}

function unsupportedPlatform(name: string, platform: string): HogError {
    return new HogError(
        'mcp_unsupported_platform',
        `hog doesn't know where ${name} keeps its MCP servers on ${platform}.`,
        'Pass `--agent` with another agent.'
    )
}

function appData(name: string, env: Env): string {
    if (!env.APPDATA) {
        throw new HogError(
            'mcp_no_app_data',
            `hog needs APPDATA to find the settings of ${name}.`,
            'Set APPDATA to your roaming app data folder, then run the command again.'
        )
    }

    return env.APPDATA
}

// An exact version, so a later release of the bridge doesn't run in the login without a new install.
const MCP_REMOTE = 'mcp-remote@0.16.5'

const LOGS_IN_ON_CONNECT = (name: string): string =>
    `${name} asks you to log in to PostHog the first time it connects to the server.`

export const MCP_CLIENTS: Readonly<Record<McpAgent, McpClient>> = {
    // The Wizard runs `claude mcp add --scope user`. hog runs no other program, so it writes the
    // project file that `claude mcp add --scope project` writes, and counts the Wizard's entry too.
    'claude-code': {
        name: 'Claude Code',
        file: ({ root }) => ({ path: join(root, '.mcp.json'), scope: 'project' }),
        format: { kind: 'json', serversKey: 'mcpServers', entry: (url) => ({ type: 'http', url }) },
        elsewhere: ({ home, root }) => [
            { path: join(home, '.claude.json'), keys: ['mcpServers'] },
            { path: join(home, '.claude.json'), keys: ['projects', root, 'mcpServers'] },
        ],
        afterAdd:
            'Claude Code asks you to approve the server in this repository. Then run `claude mcp login posthog` to log in to PostHog.',
    },
    cursor: {
        name: 'Cursor',
        file: ({ home }) => ({ path: join(home, '.cursor', 'mcp.json'), scope: 'user' }),
        format: { kind: 'json', serversKey: 'mcpServers', entry: (url) => ({ url }) },
        afterAdd: LOGS_IN_ON_CONNECT('Cursor'),
    },
    codex: {
        name: 'Codex',
        file: ({ runtime, home }) => {
            const folder = runtime.env.CODEX_HOME
                ? resolve(runtime.cwd(), runtime.env.CODEX_HOME)
                : join(home, '.codex')
            return { path: join(folder, 'config.toml'), scope: 'user' }
        },
        format: { kind: 'codex-toml' },
        afterAdd: 'Run `codex mcp login posthog` to log in to PostHog.',
    },
    vscode: {
        name: 'VS Code',
        file: ({ runtime, home }) => {
            const user = ['Code', 'User', 'mcp.json']
            switch (runtime.platform) {
                case 'darwin':
                    return { path: join(home, 'Library', 'Application Support', ...user), scope: 'user' }
                case 'win32':
                    return { path: join(appData('VS Code', runtime.env), ...user), scope: 'user' }
                case 'linux':
                    return { path: join(home, '.config', ...user), scope: 'user' }
                default:
                    throw unsupportedPlatform('VS Code', runtime.platform)
            }
        },
        format: { kind: 'json', serversKey: 'servers', entry: (url) => ({ type: 'http', url }) },
        afterAdd: LOGS_IN_ON_CONNECT('VS Code'),
    },
    zed: {
        name: 'Zed',
        file: ({ runtime, home }) => {
            if (runtime.platform !== 'darwin' && runtime.platform !== 'linux') {
                throw unsupportedPlatform('Zed', runtime.platform)
            }

            const xdg = runtime.platform === 'linux' ? runtime.env.XDG_CONFIG_HOME : undefined
            return { path: join(xdg || join(home, '.config'), 'zed', 'settings.json'), scope: 'user' }
        },
        format: { kind: 'json', serversKey: 'context_servers', entry: (url) => ({ enabled: true, url }) },
        afterAdd: LOGS_IN_ON_CONNECT('Zed'),
    },
    opencode: {
        name: 'opencode',
        file: async ({ runtime, home }) => {
            const { env } = runtime
            const folder =
                env.OPENCODE_CONFIG_DIR ||
                (env.XDG_CONFIG_HOME ? join(env.XDG_CONFIG_HOME, 'opencode') : join(home, '.config', 'opencode'))

            const jsonc = join(folder, 'opencode.jsonc')
            return { path: (await runtime.exists(jsonc)) ? jsonc : join(folder, 'opencode.json'), scope: 'user' }
        },
        format: { kind: 'json', serversKey: 'mcp', entry: (url) => ({ type: 'remote', url }) },
        afterAdd: LOGS_IN_ON_CONNECT('opencode'),
    },
    // Claude Desktop runs local servers only, so mcp-remote connects it to the remote server and
    // runs the OAuth login itself.
    'claude-desktop': {
        name: 'Claude Desktop',
        file: ({ runtime, home }) => {
            const file = 'claude_desktop_config.json'
            switch (runtime.platform) {
                case 'darwin':
                    return { path: join(home, 'Library', 'Application Support', 'Claude', file), scope: 'user' }
                case 'win32':
                    return { path: join(appData('Claude Desktop', runtime.env), 'Claude', file), scope: 'user' }
                default:
                    throw unsupportedPlatform('Claude Desktop', runtime.platform)
            }
        },
        format: {
            kind: 'json',
            serversKey: 'mcpServers',
            entry: (url) => ({ command: 'npx', args: ['-y', MCP_REMOTE, url] }),
        },
        afterAdd: `Restart Claude Desktop. ${LOGS_IN_ON_CONNECT('It')}`,
    },
}

export function detectedMcpAgent(detected: string | undefined, env: Env): McpAgent | undefined {
    const known = detected === undefined ? undefined : knownAgent(detected, env)
    return MCP_AGENTS.find((agent) => agent === known)
}

export function whereFor(runtime: Runtime, root: string): Where {
    const home = runtime.homeDir()
    if (!home) {
        throw new HogError(
            'no_home_directory',
            "hog couldn't find your home folder, where your agent keeps its MCP servers.",
            'Set HOME to your home folder.'
        )
    }

    return { runtime, home, root }
}

// The MCP server serves PostHog Cloud only, so a self-hosted host gets no entry that would fail later.
export async function mcpUrl(ctx: Context): Promise<string> {
    const { choice } = chooseLogin(await readSettings(ctx.runtime), await ctx.loginQuery())
    if (choice.host === null) {
        return MCP_URLS.us
    }

    const region = regionOf(choice.host)
    if (region === undefined) {
        throw new HogError(
            'mcp_self_hosted',
            `${escapeControls(choice.host)} isn't PostHog Cloud, and the PostHog MCP server only connects to PostHog Cloud.`,
            'To add it for a PostHog Cloud project, pass `--host https://us.posthog.com` or `--host https://eu.posthog.com`.'
        )
    }

    return MCP_URLS[region]
}

type Jsonc = typeof import('jsonc-parser')

const loadJsonc = (): Promise<Jsonc> => import('jsonc-parser')

function invalidConfig(path: string, problem: string): HogError {
    return new HogError(
        'invalid_mcp_config',
        `${escapeControls(path)} ${problem}`,
        `Fix ${escapeControls(basename(path))}, then run the command again. hog changes nothing in it until then.`
    )
}

function readJsonConfig(jsonc: Jsonc, path: string, text: string): Record<string, unknown> {
    if (text.trim() === '') {
        return {}
    }

    const errors: ParseError[] = []
    const value: unknown = jsonc.parse(text, errors, { allowTrailingComma: true })
    const config = JsonObject.safeParse(value)
    if (errors.length > 0 || !config.success) {
        throw invalidConfig(path, "isn't a JSON object hog can read.")
    }

    return config.data
}

function serversAt(config: Record<string, unknown>, keys: readonly string[]): Record<string, unknown> | undefined {
    let node: unknown = config
    for (const key of keys) {
        const object = JsonObject.safeParse(node)
        node = object.success ? object.data[key] : undefined
    }

    return JsonObject.safeParse(node).data
}

// Codex gives a server 10 seconds to start, which a remote OAuth handshake can take longer than.
const CODEX_STARTUP_TIMEOUT_SEC = 30

const ServerFields = z.object({
    url: z.string().optional(),
    command: z.string().optional(),
    args: z.array(z.string()).optional(),
})

const MCP_REMOTE_PACKAGE = /^mcp-remote(?:@[0-9A-Za-z][0-9A-Za-z._+-]*)?$/

const COMMAND_FIELDS = new Set(['command', 'args', 'startup_timeout_sec', 'tool_timeout_sec'])

interface ServerEntry {
    url: string | undefined
    command: boolean
    posthog: boolean
}

function isPostHogUrl(url: string): boolean {
    const origin = URL.parse(url)?.origin
    return origin !== undefined && POSTHOG_ORIGINS.has(origin)
}

// A server with a command runs that command, whatever its `url` says. It reaches a URL only through
// mcp-remote.
function connectsTo(server: CodexServer): string | undefined {
    if (server.command === undefined) {
        return server.url
    }

    const bridge = server.args.findIndex((arg) => MCP_REMOTE_PACKAGE.test(arg))
    return server.command === 'npx' && bridge >= 0 ? server.args[bridge + 1] : undefined
}

function isMcpRemoteAsHogWritesIt(server: CodexServer): boolean {
    const [flag, ...rest] = server.args
    const [bridge, url, ...extra] = flag === '-y' || flag === '--yes' ? rest : server.args

    return (
        server.command === 'npx' &&
        bridge !== undefined &&
        MCP_REMOTE_PACKAGE.test(bridge) &&
        url !== undefined &&
        isPostHogUrl(url) &&
        extra.length === 0 &&
        server.fields.every((field) => COMMAND_FIELDS.has(field))
    )
}

// npx run from a repository resolves `node_modules/.bin/mcp-remote` before the registry, so a
// command in a project file runs whatever the repository ships.
function serverEntry(server: CodexServer, scope: McpFile['scope']): ServerEntry {
    const url = connectsTo(server)
    const command = server.command !== undefined
    const posthog = command
        ? scope === 'user' && isMcpRemoteAsHogWritesIt(server)
        : url !== undefined && isPostHogUrl(url)

    return { url, command, posthog }
}

// `claude mcp add` writes `"type": "stdio"` and an empty `env` next to every command.
function launchFields(entry: Record<string, unknown>): string[] {
    return Object.keys(entry).filter((key) => {
        if (key === 'type') {
            return entry.type !== 'stdio'
        }

        const env = key === 'env' ? JsonObject.safeParse(entry.env).data : undefined
        return env === undefined || Object.keys(env).length > 0
    })
}

function jsonServerEntry(
    servers: Record<string, unknown> | undefined,
    scope: McpFile['scope']
): ServerEntry | undefined {
    if (servers === undefined || !Object.hasOwn(servers, SERVER_NAME)) {
        return undefined
    }

    const entry = JsonObject.safeParse(servers[SERVER_NAME]).data ?? {}
    const fields = ServerFields.safeParse(entry).data
    return serverEntry({ ...fields, args: fields?.args ?? [], fields: launchFields(entry) }, scope)
}

function findServer(jsonc: Jsonc, client: McpClient, file: McpFile, text: string | undefined): ServerEntry | undefined {
    if (text === undefined) {
        return undefined
    }

    if (client.format.kind === 'codex-toml') {
        const server = codexServer(text, SERVER_NAME)
        return server && serverEntry(server, file.scope)
    }

    const config = readJsonConfig(jsonc, file.path, text)
    const { serversKey } = client.format
    if (config[serversKey] !== undefined && !JsonObject.safeParse(config[serversKey]).success) {
        throw invalidConfig(file.path, `has a "${serversKey}" value that isn't an object.`)
    }

    return jsonServerEntry(serversAt(config, [serversKey]), file.scope)
}

// A URL can carry credentials in its user info or query, so the error shows only where it points.
function displayUrl(raw: string): string {
    try {
        const { origin, pathname } = new URL(raw)
        return `${origin}${pathname}`
    } catch {
        return 'a URL hog cannot read'
    }
}

function foreignServer(path: string, entry: ServerEntry): HogError {
    const file = escapeControls(path)
    const url = entry.url !== undefined && !isPostHogUrl(entry.url) ? displayUrl(entry.url) : undefined
    const problem =
        url !== undefined
            ? `points at ${escapeControls(url)}, not PostHog's MCP server.`
            : entry.command
              ? "runs a command that hog didn't write, so hog can't tell what it connects to."
              : "doesn't connect to PostHog's MCP server."
    return new HogError(
        'mcp_foreign_server',
        `The "${SERVER_NAME}" MCP server in ${file} ${problem}`,
        "Pass `--force` to replace it with PostHog's MCP server.",
        undefined,
        { path, url: url ?? null }
    )
}

// jsonc-parser reads the last of two equal keys, and its edits change the first, so a forced
// replacement would leave the other entry as the one the agent reads.
function assertOneKeyEach(jsonc: Jsonc, client: McpClient, path: string, text: string, keys: readonly string[]): void {
    let node = jsonc.parseTree(text, [], { allowTrailingComma: true })
    for (const key of keys) {
        const matches =
            node?.type === 'object' ? (node.children ?? []).filter((child) => child.children?.[0]?.value === key) : []
        if (matches.length > 1) {
            throw invalidConfig(path, `has "${key}" more than once, so hog can't tell which one ${client.name} reads.`)
        }

        node = matches[0]?.children?.[1]
    }
}

function withServer(jsonc: Jsonc, client: McpClient, path: string, text: string, url: string): string {
    if (client.format.kind === 'codex-toml') {
        const edited = withCodexServer(text, SERVER_NAME, {
            url: `"${url}"`,
            startup_timeout_sec: String(CODEX_STARTUP_TIMEOUT_SEC),
        })
        if (edited === undefined) {
            throw new HogError(
                'mcp_config_not_editable',
                `${escapeControls(path)} writes mcp_servers inline or with dotted keys, so hog can't add a [mcp_servers.${SERVER_NAME}] table to it.`,
                `Move the servers in ${escapeControls(basename(path))} into [mcp_servers.<name>] tables, then run the command again.`
            )
        }

        return edited
    }

    const { serversKey, entry } = client.format
    assertOneKeyEach(jsonc, client, path, text, [serversKey, SERVER_NAME])

    const edits = jsonc.modify(text, [serversKey, SERVER_NAME], entry(url), {
        formattingOptions: { tabSize: 2, insertSpaces: true },
    })
    return jsonc.applyEdits(text, edits)
}

async function readOptional(runtime: Runtime, path: string): Promise<string | undefined> {
    return (await runtime.exists(path)) ? runtime.readFile(path) : undefined
}

// Only a lookup, so a file another tool keeps that hog can't read, or an entry there that connects
// to another server, counts as having no entry.
async function findElsewhere(jsonc: Jsonc, client: McpClient, where: Where): Promise<string | undefined> {
    for (const { path, keys } of client.elsewhere?.(where) ?? []) {
        const servers = await readOptional(where.runtime, path)
            .then((text) => (text === undefined ? undefined : serversAt(readJsonConfig(jsonc, path, text), keys)))
            .catch(() => undefined)
        if (jsonServerEntry(servers, 'user')?.posthog) {
            return path
        }
    }

    return undefined
}

function unsafePath(file: McpFile, root: string, target: string | undefined): HogError {
    const where = target === undefined ? 'a missing file' : escapeControls(target)
    return new HogError(
        'unsafe_mcp_config_path',
        file.scope === 'project'
            ? `${escapeControls(file.path)} links to ${where}, outside ${escapeControls(root)}. hog doesn't write through links that leave the repository.`
            : `${escapeControls(file.path)} links to ${where}, so hog can't tell where a write would land.`,
        `Replace ${escapeControls(basename(file.path))} with a regular file, or link it to an existing file${file.scope === 'project' ? ' inside the repository' : ''}. Then run the command again.`
    )
}

// Where a write to the file lands. A link is followed, so a settings file kept in a dotfiles
// repository stays a link. A link to a missing file is refused, because the write would create
// whatever file it names.
async function writeTarget(runtime: Runtime, file: McpFile, root: string): Promise<string> {
    const folder = await realWritePath(runtime, dirname(file.path))
    const path = join(folder, basename(file.path))
    const target = (await runtime.exists(folder)) ? await runtime.realPath(path).catch(() => undefined) : path

    if (target === undefined || (file.scope === 'project' && !isInside(await runtime.realPath(root), target))) {
        throw unsafePath(file, root, target)
    }

    return target
}

export interface AddedServer {
    agent: McpAgent
    path: string
    status: 'added' | 'replaced' | 'already_added'
}

export interface PlannedAdd {
    agent: McpAgent
    file: McpFile
}

// Every path is worked out before the first write, so an agent hog can't serve on this platform
// fails the command before another agent's file changes.
export async function planAdd(agents: readonly McpAgent[], where: Where): Promise<PlannedAdd[]> {
    return Promise.all(agents.map(async (agent) => ({ agent, file: await MCP_CLIENTS[agent].file(where) })))
}

export async function addServer(plan: PlannedAdd, where: Where, url: string, force: boolean): Promise<AddedServer> {
    const { runtime, root } = where
    const { agent, file } = plan
    const client = MCP_CLIENTS[agent]
    const jsonc = await loadJsonc()

    const target = await writeTarget(runtime, file, root)
    const before = await readOptional(runtime, target)
    const existing = findServer(jsonc, client, file, before)

    if (!force) {
        if (existing && !existing.posthog) {
            throw foreignServer(file.path, existing)
        }

        const found = existing ? file.path : await findElsewhere(jsonc, client, where)
        if (found !== undefined) {
            return { agent, path: found, status: 'already_added' }
        }
    }

    const after = withServer(jsonc, client, file.path, before ?? '', url)
    await (before === undefined ? runtime.writeFile(target, after) : runtime.replaceFile(target, after))

    return { agent, path: file.path, status: existing ? 'replaced' : 'added' }
}

export type McpServerCheck = { status: 'configured' | 'missing' } | { status: 'foreign'; path: string }

export async function checkMcpServer(agent: McpAgent, where: Where): Promise<McpServerCheck> {
    const client = MCP_CLIENTS[agent]
    const jsonc = await loadJsonc()

    try {
        const file = await client.file(where)
        const existing = findServer(jsonc, client, file, await readOptional(where.runtime, file.path))
        if (existing) {
            return existing.posthog ? { status: 'configured' } : { status: 'foreign', path: file.path }
        }
    } catch {
        return { status: 'missing' }
    }

    return { status: (await findElsewhere(jsonc, client, where)) === undefined ? 'missing' : 'configured' }
}

export const McpAgentName = z.enum(MCP_AGENTS, {
    error: (issue) => `hog can't add the MCP server to "${String(issue.input)}".`,
})
