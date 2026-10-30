import type {
    ApiConnection,
    ApiToolError,
    ApiToolLibrary,
    ApiToolResult,
    ApiToolSummary,
} from '@posthog/mcp/src/cli/library-types'

import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { VERSION } from '@/version'

import { ApiError } from './api'

export interface ToolGroup {
    slug: string
    name: string
    tools: ApiToolSummary[]
}

export type ToolKind = 'read' | 'write' | 'destructive'

// One tool as `hog api tools` and `hog api search` list it. `usable` and `missingScopes` are
// null without credentials, so people can browse before `hog auth login`.
export interface ToolRow {
    name: string
    group: string
    kind: ToolKind
    summary: string
    usable: boolean | null
    missingScopes: string[] | null
}

const SCOPES_HINT =
    'Run `hog auth login` to create a key with the scopes the API tools need, or add the scopes to the key in PostHog under Settings, Personal API keys.'

// "Events & properties" becomes "events-properties".
export function groupSlug(name: string): string {
    return name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
}

export function groupTools(tools: readonly ApiToolSummary[]): ToolGroup[] {
    const groups = new Map<string, ToolGroup>()
    for (const tool of tools) {
        const slug = groupSlug(tool.group)
        const group = groups.get(slug) ?? { slug, name: tool.group, tools: [] }
        group.tools.push(tool)
        groups.set(slug, group)
    }
    return [...groups.values()].sort((a, b) => a.slug.localeCompare(b.slug))
}

// Takes the slug or the group's name, so `feature-flags` and "Feature flags" both work.
export function findGroup(library: ApiToolLibrary, query: string): ToolGroup {
    const group = groupTools(library.tools()).find((candidate) => candidate.slug === groupSlug(query))
    if (!group) {
        throw new HogError(
            'unknown_group',
            `There is no tool group named "${query}".`,
            'Run `hog api groups` to list them.'
        )
    }
    return group
}

export function findTool(library: ApiToolLibrary, name: string): ApiToolSummary {
    const tool = library.tools().find((candidate) => candidate.name === name)
    if (!tool) {
        throw new HogError(
            'unknown_tool',
            `There is no tool named "${name}".`,
            'Run `hog api search <words>` to find tools by name and description.'
        )
    }
    return tool
}

export function toolKind(tool: ApiToolSummary): ToolKind {
    return tool.destructive ? 'destructive' : tool.readOnly ? 'read' : 'write'
}

export function toolRow(library: ApiToolLibrary, tool: ApiToolSummary, granted: string[] | undefined): ToolRow {
    const missingScopes = granted ? library.missingScopes(granted, tool.requiredScopes) : null
    return {
        name: tool.name,
        group: groupSlug(tool.group),
        kind: toolKind(tool),
        summary: tool.summary,
        usable: missingScopes ? missingScopes.length === 0 : null,
        missingScopes,
    }
}

export async function apiConnection(
    ctx: Context,
    scope: { projectId?: string | undefined; organizationId?: string | undefined } = {}
): Promise<ApiConnection> {
    // An empty ID, often an unset shell variable, would fall back to another project silently.
    for (const [flag, value] of [
        ['--project-id', scope.projectId],
        ['--organization-id', scope.organizationId],
    ] as const) {
        if (value !== undefined && value.trim() === '') {
            throw new HogError('invalid_input', `${flag} is empty.`, `Pass an ID, or leave out ${flag}.`, EXIT_USAGE)
        }
    }
    const credentials = await ctx.credentials()
    // The saved project can belong to another organization, so an organization override drops it.
    const projectId = scope.projectId ?? (scope.organizationId ? undefined : credentials.projectId)
    return {
        apiKey: credentials.apiKey,
        host: credentials.host,
        ...(projectId ? { projectId } : {}),
        ...(scope.organizationId ? { organizationId: scope.organizationId } : {}),
        clientName: 'hog',
        clientVersion: VERSION,
    }
}

export function missingScopesError(tool: string, scopes: readonly string[]): HogError {
    return new HogError(
        'missing_scopes',
        `The personal API key needs ${scopes.join(', ')} to call ${tool}.`,
        SCOPES_HINT
    )
}

export function toHogError(error: ApiToolError, tool?: string): HogError {
    switch (error.code) {
        case 'permission_denied':
            return error.missingScope && tool
                ? missingScopesError(tool, [error.missingScope])
                : new ApiError(403, undefined, 'permission_denied', error.message, SCOPES_HINT)
        case 'validation_error':
        case 'invalid_input':
            return new HogError(
                error.code,
                error.message,
                tool ? `Run \`hog api schema ${tool}\` to see the input it takes.` : undefined
            )
        case 'needs_confirmation':
            return new HogError(error.code, error.message, 'Run it again with --confirm.')
        case 'ai_consent_required':
            return new HogError(
                error.code,
                error.message,
                'An organization admin can allow AI data processing in PostHog under Organization settings.'
            )
        case 'rate_limited':
            return new ApiError(429, undefined, error.code, error.message, 'Wait a minute, then run it again.')
        case 'unreachable':
            return new HogError(error.code, error.message, 'Check the host and your network connection.')
        case 'api_error': {
            const hints: Record<number, string> = {
                401: 'Check that the personal API key is valid.',
                404: 'Check the IDs in the input, and the project ID.',
            }
            const status = error.status ?? 500
            return new ApiError(status, undefined, `http_${status}`, error.message, hints[status])
        }
        case 'tool_error':
            return new HogError(error.code, error.message)
    }
}

export function unwrap<T>(result: ApiToolResult<T>, tool?: string): T {
    if (!result.ok) {
        throw toHogError(result.error, tool)
    }
    return result.value
}

const SCOPE_LOOKUP_MS = 10_000

// Undefined when the scopes are unknown, so browsing still works on a failed or stalled lookup.
export async function grantedScopes(ctx: Context, library: ApiToolLibrary): Promise<string[] | undefined> {
    let connection: ApiConnection
    try {
        connection = await apiConnection(ctx)
    } catch (error) {
        if (error instanceof HogError && error.code === 'not_authenticated') {
            return undefined
        }
        throw error
    }
    // The abort also ends the request, so a stalled lookup doesn't keep the process alive after the output.
    const deadline = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const stalled = new Promise<undefined>((resolve) => {
        timer = setTimeout(() => {
            deadline.abort()
            resolve(undefined)
        }, SCOPE_LOOKUP_MS)
    })
    const lookup = library
        .keyAccess(connection, { signal: deadline.signal })
        .then((result) => (result.ok ? result.value.scopes : undefined))
    try {
        return await Promise.race([lookup, stalled])
    } finally {
        clearTimeout(timer)
    }
}
