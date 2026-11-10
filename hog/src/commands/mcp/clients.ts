import type { ParseError } from 'jsonc-parser'
import { basename, dirname, join } from 'node:path'
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
        file: ({ home }) => ({ path: join(home, '.codex', 'config.toml'), scope: 'user' }),
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
            entry: (url) => ({ command: 'npx', args: ['-y', 'mcp-remote@latest', url] }),
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

// Two ways to write one TOML table header, bare and quoted. Matching only one would append a
// second definition of the table, which Codex rejects with the whole config.
const CODEX_SECTION = new RegExp(`^\\[mcp_servers\\.(?:${SERVER_NAME}|"${SERVER_NAME}")\\][ \\t]*$`, 'm')

// Codex gives a server 10 seconds to start, which a remote OAuth handshake can take longer than.
const CODEX_STARTUP_TIMEOUT_SEC = 30

// TOML keys come in any order, so the whole section body is searched.
function setTomlKey(body: string, key: string, value: string): string {
    const existing = new RegExp(`^[ \\t]*${key}[ \\t]*=.*$`, 'm')
    return existing.test(body) ? body.replace(existing, `${key} = ${value}`) : `\n${key} = ${value}${body}`
}

// Edits the text in place, so the other servers, comments and key order survive, as the Wizard does.
function withCodexServer(contents: string, url: string): string {
    const header = CODEX_SECTION.exec(contents)
    if (!header) {
        const gap = contents === '' || contents.endsWith('\n\n') ? '' : '\n'
        const pad = contents === '' || contents.endsWith('\n') ? '' : '\n'
        return `${contents}${pad}${gap}[mcp_servers.${SERVER_NAME}]\nurl = "${url}"\nstartup_timeout_sec = ${CODEX_STARTUP_TIMEOUT_SEC}\n`
    }

    const start = header.index + header[0].length
    const next = /^\[/m.exec(contents.slice(start))
    const end = next ? start + next.index : contents.length
    const body = setTomlKey(
        setTomlKey(contents.slice(start, end), 'url', `"${url}"`),
        'startup_timeout_sec',
        String(CODEX_STARTUP_TIMEOUT_SEC)
    )

    return contents.slice(0, start) + body + contents.slice(end)
}

function hasServer(jsonc: Jsonc, client: McpClient, path: string, text: string | undefined): boolean {
    if (text === undefined) {
        return false
    }

    if (client.format.kind === 'codex-toml') {
        return CODEX_SECTION.test(text)
    }

    const config = readJsonConfig(jsonc, path, text)
    const { serversKey } = client.format
    if (config[serversKey] !== undefined && !JsonObject.safeParse(config[serversKey]).success) {
        throw invalidConfig(path, `has a "${serversKey}" value that isn't an object.`)
    }

    return Object.hasOwn(serversAt(config, [serversKey]) ?? {}, SERVER_NAME)
}

function withServer(jsonc: Jsonc, client: McpClient, text: string, url: string): string {
    if (client.format.kind === 'codex-toml') {
        return withCodexServer(text, url)
    }

    const { serversKey, entry } = client.format
    const edits = jsonc.modify(text, [serversKey, SERVER_NAME], entry(url), {
        formattingOptions: { tabSize: 2, insertSpaces: true },
    })
    return jsonc.applyEdits(text, edits)
}

async function readOptional(runtime: Runtime, path: string): Promise<string | undefined> {
    return (await runtime.exists(path)) ? runtime.readFile(path) : undefined
}

// Only a lookup, so a file another tool keeps that hog can't read counts as having no entry.
async function findElsewhere(jsonc: Jsonc, client: McpClient, where: Where): Promise<string | undefined> {
    for (const { path, keys } of client.elsewhere?.(where) ?? []) {
        const servers = await readOptional(where.runtime, path)
            .then((text) => (text === undefined ? undefined : serversAt(readJsonConfig(jsonc, path, text), keys)))
            .catch(() => undefined)
        if (servers !== undefined && Object.hasOwn(servers, SERVER_NAME)) {
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
    const present = hasServer(jsonc, client, file.path, before)

    if (!force) {
        const found = present ? file.path : await findElsewhere(jsonc, client, where)
        if (found !== undefined) {
            return { agent, path: found, status: 'already_added' }
        }
    }

    const after = withServer(jsonc, client, before ?? '', url)
    await (before === undefined ? runtime.writeFile(target, after) : runtime.replaceFile(target, after))

    return { agent, path: file.path, status: present ? 'replaced' : 'added' }
}

export async function hasMcpServer(agent: McpAgent, where: Where): Promise<boolean> {
    const client = MCP_CLIENTS[agent]
    const jsonc = await loadJsonc()

    try {
        const { path } = await client.file(where)
        if (hasServer(jsonc, client, path, await readOptional(where.runtime, path))) {
            return true
        }
    } catch {
        return false
    }

    return (await findElsewhere(jsonc, client, where)) !== undefined
}

export const McpAgentName = z.enum(MCP_AGENTS, {
    error: (issue) => `hog can't add the MCP server to "${String(issue.input)}".`,
})
