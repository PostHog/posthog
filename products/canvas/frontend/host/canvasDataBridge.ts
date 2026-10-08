import { z } from 'zod'

import api from 'lib/api'
import { apiHostOrigin } from 'lib/utils/apiHost'

import { DashboardFilter, HogQLVariable, NodeKind } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

import {
    canvasesActionsInvoke,
    canvasesActionsRetrieve,
    canvasesConnectorsCall,
    canvasesRequestAgentCreate,
    canvasesStateRetrieve,
    canvasesStateSet,
} from '../generated/api'
import type {
    CanvasActionDefinitionApi,
    CanvasConnectorCallResultApi,
    CanvasStateEntryApi,
} from '../generated/api.schemas'
import {
    CanvasConnectorCallInput,
    canvasAgentRequestInputSchema,
    canvasConnectorCallInputSchema,
} from './canvasProtocol'
import { CanvasReadCache } from './canvasReadCache'

const MAX_RESULT_ROWS = 1_000
const MAX_RESULT_BYTES = 2 * 1024 * 1024
const DEFAULT_READ_TTL_SECONDS = 5 * 60
// Connector results describe live external state, so they go stale faster than an insight.
const CONNECTOR_READ_TTL_SECONDS = 60
const MAX_STATE_PAGES = 20
const canvasQuerySchema = z.object({ kind: z.nativeEnum(NodeKind) }).passthrough()
// pinned: `$lib` value on events a canvas captures, shared with PostHog Desktop
const CANVAS_CAPTURE_LIB = 'posthog-canvas'

export interface CanvasConnectorPermissionRequest {
    provider: string
    tool: string
    arguments?: Record<string, unknown>
    /** `canvas` asks once per canvas version, `tool` approves a single call. */
    reason: 'canvas' | 'tool'
}

export interface CanvasDataBridgeContext {
    projectId: string
    canvasId: string
    /** The source version the running code came from. Connector consent is scoped to it. */
    sourceVersionId: string | null
    /** The current project's public capture token. */
    captureToken: string | null
    distinctId: string | null
}

export interface CanvasActionConfirmation {
    action: CanvasActionDefinitionApi
    payload: Record<string, unknown>
}

export interface CanvasDataBridgePrompts {
    confirmAction: (request: CanvasActionConfirmation) => Promise<boolean>
    confirmAgentRequest: (prompt: string) => Promise<boolean>
    requestConnectorPermission: (request: CanvasConnectorPermissionRequest) => Promise<boolean>
    hasUserActivation: () => boolean
}

interface CanvasDataResult {
    columns: string[]
    results: unknown[]
    hogql?: string
    insight?: { name: string | null; kind: string | null; display: string | null }
}

type QueryNode = { kind?: string; source?: QueryNode | null; variables?: Record<string, unknown> | null }

function refreshSeconds(value: unknown): number | undefined {
    if (value === undefined) {
        return undefined
    }
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 30 || value > 86_400) {
        throw new Error('refresh must be an integer between 30 and 86400 seconds')
    }
    return value
}

function normalizeHogQLRows(results: unknown[]): unknown[] {
    return results.map((row) => (Array.isArray(row) ? row : [row]))
}

function boundedResult(result: CanvasDataResult): CanvasDataResult {
    if (result.results.length > MAX_RESULT_ROWS || JSON.stringify(result).length > MAX_RESULT_BYTES) {
        throw new Error('Canvas data result exceeds the result limit')
    }
    return result
}

// SQL variables sit on the HogQLQuery node, under one or more wrapper nodes.
function resolvedVariables(query: QueryNode | null | undefined): Record<string, unknown> {
    let node = query
    for (let depth = 0; node && depth < 5; depth++) {
        if (node.variables) {
            return Object.fromEntries(
                Object.values(node.variables)
                    .map((variable) => variable as { code_name?: unknown; value?: unknown })
                    .filter((variable) => typeof variable?.code_name === 'string')
                    .map((variable) => [variable.code_name as string, variable.value])
            )
        }
        node = node.source
    }
    return {}
}

// The API drops an unknown variable without an error, and the insight then returns its
// saved defaults, which look plausible. So check what the server actually applied.
function assertVariablesApplied(
    requested: Record<string, unknown> | undefined,
    resolved: Record<string, unknown>,
    shortId: string
): void {
    for (const [codeName, value] of Object.entries(requested ?? {})) {
        if (!(codeName in resolved)) {
            throw new Error(`Insight "${shortId}" has no SQL variable "${codeName}"`)
        }
        if (JSON.stringify(resolved[codeName] ?? null) !== JSON.stringify(value ?? null)) {
            throw new Error(`SQL variable "${codeName}" was not applied to insight "${shortId}"`)
        }
    }
}

/**
 * Resolves the `ph.*` data requests a canvas sends. The web app's session runs every
 * call, and the iframe only ever sees the result. Each canvas passes each request
 * through `assertCanvasCapability` before it reaches here.
 */
export class CanvasDataBridge {
    private readonly cache = new CanvasReadCache()
    private readonly connectorConsent = new Map<string, boolean>()

    constructor(
        private readonly context: () => CanvasDataBridgeContext,
        private readonly prompts: CanvasDataBridgePrompts
    ) {}

    async handle(method: string, payload: unknown): Promise<unknown> {
        const input = (payload ?? {}) as Record<string, unknown>
        switch (method) {
            case 'query':
                return this.query(input)
            case 'loadInsight':
                return this.loadInsight(input)
            case 'capture':
                return this.capture(input)
            case 'stateGet':
                return this.stateGet(input)
            case 'stateSet':
                return this.stateSet(input)
            case 'stateList':
                return this.stateList(input)
            case 'actionInvoke':
                return this.actionInvoke(input)
            case 'agentRequest':
                return this.agentRequest(payload)
            case 'connectorCall':
                return this.connectorCall(payload)
            case 'run':
                throw new Error('ph.run is not available yet')
            default:
                throw new Error(`Unknown data method "${method}"`)
        }
    }

    private async query(input: Record<string, unknown>): Promise<CanvasDataResult> {
        const typed = input.query != null && typeof input.query === 'object'
        const hogql = typeof input.hogql === 'string' && input.hogql.length > 0 ? input.hogql : null
        if (!typed && !hogql) {
            throw new Error('ph.query requires a typed query node or a HogQL string')
        }
        if (input.params != null && (typeof input.params !== 'object' || Object.keys(input.params).length > 0)) {
            throw new Error('ph.query parameters are not supported. Use a typed query with variables instead.')
        }
        const refresh = refreshSeconds(input.refresh)
        const node = canvasQuerySchema.parse(typed ? input.query : { kind: NodeKind.HogQLQuery, query: hogql })
        return this.cache.read(
            'query',
            { node, params: input.params },
            refresh ?? DEFAULT_READ_TTL_SECONDS,
            async () => {
                const response = (await api.query(node, { refresh: 'blocking' })) as Record<string, unknown>
                if (typeof response.error === 'string' && response.error) {
                    throw new Error(response.error)
                }
                const results = Array.isArray(response.results) ? response.results : []
                return boundedResult({
                    columns: Array.isArray(response.columns) ? response.columns.map(String) : [],
                    // Typed nodes return series objects, which a row wrapper would read as zero.
                    results: typed ? results : normalizeHogQLRows(results),
                    ...(typeof response.hogql === 'string' ? { hogql: response.hogql } : {}),
                })
            }
        )
    }

    private async loadInsight(input: Record<string, unknown>): Promise<CanvasDataResult> {
        const shortId = input.shortId
        if (typeof shortId !== 'string' || !shortId) {
            throw new Error('ph.loadInsight(shortId) requires an insight short id')
        }
        const dateRange = input.dateRange as DashboardFilter | undefined
        const variables = input.variables as Record<string, unknown> | undefined
        return this.cache.read(
            'loadInsight',
            { shortId, dateRange, variables },
            refreshSeconds(input.refresh) ?? DEFAULT_READ_TTL_SECONDS,
            async () => {
                const variablesOverride =
                    variables && Object.keys(variables).length > 0
                        ? (Object.fromEntries(
                              Object.entries(variables).map(([codeName, value]) => [
                                  codeName,
                                  { code_name: codeName, value },
                              ])
                          ) as unknown as Record<string, HogQLVariable>)
                        : undefined
                const response = await api.insights.loadInsight(
                    shortId as InsightShortId,
                    false,
                    'blocking',
                    dateRange ?? undefined,
                    variablesOverride
                )
                const insight = response.results[0] as Record<string, unknown> | undefined
                if (!insight) {
                    throw new Error(`Insight "${shortId}" not found`)
                }
                const query = insight.query as QueryNode | null | undefined
                assertVariablesApplied(variables, resolvedVariables(query), shortId)
                const source = query?.source as (QueryNode & { trendsFilter?: { display?: string } }) | undefined
                const results = Array.isArray(insight.result) ? insight.result : []
                return boundedResult({
                    columns: Array.isArray(insight.columns) ? insight.columns.map(String) : [],
                    results: query?.kind === 'HogQLQuery' ? normalizeHogQLRows(results) : results,
                    insight: {
                        name: (insight.name as string) || (insight.derived_name as string) || null,
                        kind: source?.kind ?? query?.kind ?? null,
                        display: source?.trendsFilter?.display ?? null,
                    },
                })
            }
        )
    }

    // Sends to the current project with its public token, never through the web app's
    // own analytics client, which reports into PostHog's project rather than the user's.
    private async capture(input: Record<string, unknown>): Promise<{ ok: boolean }> {
        const event = input.event
        if (typeof event !== 'string' || !event) {
            throw new Error('ph.capture(event) requires an event name')
        }
        const { captureToken, distinctId } = this.context()
        if (!captureToken) {
            throw new Error('This project has no capture key')
        }
        const response = await fetch(`${apiHostOrigin()}/i/v0/e/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'omit',
            body: JSON.stringify({
                api_key: captureToken,
                event,
                distinct_id:
                    (typeof input.distinctId === 'string' && input.distinctId) || distinctId || 'freeform-canvas',
                properties: {
                    ...(input.properties as Record<string, unknown> | undefined),
                    $lib: CANVAS_CAPTURE_LIB,
                },
            }),
        })
        if (!response.ok) {
            throw new Error(`Capture failed (${response.status})`)
        }
        return { ok: true }
    }

    private async stateGet(input: Record<string, unknown>): Promise<unknown> {
        if (typeof input.key !== 'string' || !input.key) {
            throw new Error('ph.state.get(key) requires a key')
        }
        const { projectId, canvasId } = this.context()
        // Never cached: state is the canvas's live memory, and a stale read undoes its own write.
        const response = await canvasesStateRetrieve(projectId, canvasId, {
            key: input.key,
            scope: input.scope === 'shared' ? 'shared' : 'user',
        })
        return response.entries.find((entry) => entry.key === input.key)?.value ?? null
    }

    private async stateSet(input: Record<string, unknown>): Promise<{ ok: true }> {
        if (typeof input.key !== 'string' || !input.key) {
            throw new Error('ph.state.set(key, value) requires a key')
        }
        const { projectId, canvasId } = this.context()
        await canvasesStateSet(projectId, canvasId, {
            key: input.key,
            scope: input.scope === 'shared' ? 'shared' : 'user',
            value: input.value ?? null,
        })
        return { ok: true }
    }

    private async stateList(input: Record<string, unknown>): Promise<CanvasStateEntryApi[]> {
        const { projectId, canvasId } = this.context()
        const scope = input.scope === 'shared' || input.scope === 'user' ? input.scope : undefined
        const entries: CanvasStateEntryApi[] = []
        let offset: number | null = 0
        for (let page = 0; offset !== null && page < MAX_STATE_PAGES; page++) {
            const response = await canvasesStateRetrieve(projectId, canvasId, { scope, offset })
            entries.push(...response.entries)
            offset = response.complete ? null : response.next_offset
        }
        return entries
    }

    private async actionInvoke(input: Record<string, unknown>): Promise<unknown> {
        const verb = input.verb
        if (typeof verb !== 'string' || !verb) {
            throw new Error('ph.actions.invoke(verb, payload) requires a verb')
        }
        const { projectId, canvasId } = this.context()
        const { actions } = await canvasesActionsRetrieve(projectId)
        const action = actions.find((entry) => entry.verb === verb)
        if (!action) {
            throw new Error('Unknown canvas action')
        }
        const payload = (input.payload as Record<string, unknown> | undefined) ?? {}
        // Only a verb that disables, deletes, or spends paid compute needs the viewer's confirmation; the
        // host already requires a user gesture for every invoke, as PostHog Desktop does.
        const needsConfirmation = action.destructive || action.starts_cloud_run
        if (needsConfirmation && !(await this.prompts.confirmAction({ action, payload }))) {
            throw new Error('Canvas action canceled')
        }
        return canvasesActionsInvoke(projectId, canvasId, {
            verb,
            payload,
        })
    }

    private async agentRequest(payload: unknown): Promise<{ requestOutcome: string; taskId: string }> {
        const { prompt } = canvasAgentRequestInputSchema.parse(payload)
        if (!(await this.prompts.confirmAgentRequest(prompt))) {
            throw new Error('Agent request canceled')
        }
        const { projectId, canvasId } = this.context()
        const result = await canvasesRequestAgentCreate(projectId, canvasId, { prompt })
        return { requestOutcome: result.request_outcome, taskId: result.task_id }
    }

    private async connectorCall(payload: unknown): Promise<Omit<CanvasConnectorCallResultApi, 'approval_token'>> {
        const input = canvasConnectorCallInputSchema.parse(payload)
        const { projectId, canvasId, sourceVersionId } = this.context()
        if (!sourceVersionId) {
            throw new Error('Connector calls require a saved canvas version')
        }
        await this.requireConnectorConsent(sourceVersionId, input)
        const args = { provider: input.provider, tool: input.tool, arguments: input.arguments }
        return this.cache.read(
            'connectorCall',
            { ...args, sourceVersionId },
            input.refresh ?? CONNECTOR_READ_TTL_SECONDS,
            async () => {
                const first = await canvasesConnectorsCall(projectId, canvasId, args)
                if (first.status !== 'needs_approval') {
                    return this.withoutApprovalToken(first)
                }
                if (!first.approval_token) {
                    throw new Error('This connection cannot accept one-time approval.')
                }
                const approved = await this.prompts.requestConnectorPermission({ ...args, reason: 'tool' })
                if (!approved) {
                    throw new Error('Tool access was not granted.')
                }
                const second = await canvasesConnectorsCall(projectId, canvasId, {
                    ...args,
                    approval_token: first.approval_token,
                })
                return this.withoutApprovalToken(second)
            }
        )
    }

    // The approval token is bound to this viewer and must never reach the iframe.
    private withoutApprovalToken(
        result: CanvasConnectorCallResultApi
    ): Omit<CanvasConnectorCallResultApi, 'approval_token'> {
        const { approval_token: _approvalToken, ...rest } = result
        return rest
    }

    private async requireConnectorConsent(sourceVersionId: string, input: CanvasConnectorCallInput): Promise<void> {
        const key = `${sourceVersionId}:${input.provider}:${input.tool}`
        const known = this.connectorConsent.get(key)
        // A denial sticks until the viewer interacts with the canvas again, so a render
        // loop cannot reopen the dialog.
        if (known === true || (known === false && !this.prompts.hasUserActivation())) {
            if (known) {
                return
            }
            throw new Error('Connector access was not granted. Click in the canvas to try again.')
        }
        const allowed = await this.prompts.requestConnectorPermission({
            provider: input.provider,
            tool: input.tool,
            reason: 'canvas',
        })
        this.connectorConsent.set(key, allowed)
        if (!allowed) {
            throw new Error('Connector access was not granted. Click in the canvas to try again.')
        }
    }
}
