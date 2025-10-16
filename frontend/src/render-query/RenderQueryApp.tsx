import './RenderQuery.scss'

import { useEffect, useMemo, useState } from 'react'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { useThemedHtml } from 'lib/hooks/useThemedHtml'

import { Query } from '~/queries/Query/Query'
import { AnyResponseType, InsightVizNode, Node } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isInsightVizNode } from '~/queries/utils'
import { InsightLogicProps, QueryBasedInsightModel } from '~/types'

interface RenderQueryExternalPayload {
    query?: Node | string | null
    cachedResults?: AnyResponseType | Partial<QueryBasedInsightModel> | null
    context?: QueryContext<any> | null
    insight?: Partial<QueryBasedInsightModel> | null
}

interface RenderQueryState extends RenderQueryExternalPayload {
    messages: string[]
}

interface SanitizedPayload {
    payload: RenderQueryExternalPayload
    messages: string[]
}

interface PreparedState {
    query: Node | string | null
    cachedResults: AnyResponseType | Partial<QueryBasedInsightModel> | null
    context?: QueryContext<any>
    needsResults: boolean
}

declare global {
    interface Window {
        POSTHOG_RENDER_QUERY_PAYLOAD?: unknown
    }
}

const EMPTY_PAYLOAD: SanitizedPayload = { payload: {}, messages: [] }
const SUPPORTED_KEYS = new Set(['query', 'cachedResults', 'cached_results', 'context', 'insight'])

export function RenderQueryApp(): JSX.Element {
    const [state, setState] = useState<RenderQueryState>(() => initializeState())
    const { ref, height, width } = useResizeObserver<HTMLDivElement>()

    useThemedHtml(false)

    useEffect(() => {
        window.parent?.postMessage({ event: 'posthog:render_query:ready', name: window.name }, '*')
    }, [])

    useEffect(() => {
        if (height || width) {
            window.parent?.postMessage({ event: 'posthog:dimensions', name: window.name, height, width }, '*')
        }
    }, [height, width])

    useEffect(() => {
        const onMessage = (event: MessageEvent): void => {
            const sanitized = extractPayloadFromMessage(event.data)
            if (!sanitized) {
                return
            }
            if (Object.keys(sanitized.payload).length === 0 && sanitized.messages.length === 0) {
                return
            }
            setState((previous) => applySanitizedPayload(previous, sanitized))
        }

        window.addEventListener('message', onMessage)
        return () => window.removeEventListener('message', onMessage)
    }, [])

    const prepared = useMemo(() => prepareState(state), [state])
    const hasQuery = prepared.query !== null && prepared.query !== undefined
    const canRender = hasQuery && !prepared.needsResults

    return (
        <div className="RenderQuery" ref={ref}>
            {state.messages.length > 0 && (
                <div className="RenderQuery__messages">
                    {state.messages.map((message, index) => (
                        <div className="RenderQuery__message" key={`${index}-${message}`}>
                            {message}
                        </div>
                    ))}
                </div>
            )}
            {canRender ? (
                <div className="RenderQuery__content">
                    <Query
                        query={state.query as any}
                        cachedResults={state.cachedResults ?? undefined}
                        readOnly
                        embedded
                        inSharedMode
                        context={state.context ?? undefined}
                    />
                </div>
            ) : (
                <div className="RenderQuery__placeholder">
                    {hasQuery
                        ? 'Waiting for cached results. Send cachedResults via postMessage to display data.'
                        : 'No query provided. Send a query via postMessage or include it in the iframe URL.'}
                </div>
            )}
        </div>
    )
}

function initializeState(): RenderQueryState {
    let state: RenderQueryState = {
        query: null,
        cachedResults: null,
        context: null,
        insight: null,
        messages: [],
    }

    const sources: SanitizedPayload[] = [
        sanitizePayload(window.POSTHOG_RENDER_QUERY_PAYLOAD, 'initial payload'),
        extractFromSearch(),
        extractFromHash(),
        extractFromFrameDataset(),
        extractFromWindowName(),
    ]

    for (const sanitized of sources) {
        state = applySanitizedPayload(state, sanitized)
    }

    return state
}

function applySanitizedPayload(previous: RenderQueryState, sanitized: SanitizedPayload): RenderQueryState {
    const merged = mergeIntoState(previous, sanitized.payload)
    const messages = sanitized.messages.length ? [...merged.messages, ...sanitized.messages] : merged.messages
    return { ...merged, messages }
}

function mergeIntoState(previous: RenderQueryState, payload: RenderQueryExternalPayload): RenderQueryState {
    if (!payload) {
        return { ...previous }
    }
    const next: RenderQueryState = { ...previous }
    const keys: (keyof RenderQueryExternalPayload)[] = ['query', 'cachedResults', 'context', 'insight']
    for (const key of keys) {
        if (Object.prototype.hasOwnProperty.call(payload, key)) {
            const value = payload[key]
            if (value !== undefined) {
                next[key] = value
            }
        }
    }
    return next
}

function prepareState(state: RenderQueryState): PreparedState {
    let query = state.query ?? null
    let cachedResults = state.cachedResults ?? null
    let context = state.context ?? undefined
    let needsResults = false

    if (query && typeof query === 'object' && isInsightVizNode(query)) {
        const queryNode = query as InsightVizNode
        const existingInsightProps = (context?.insightProps as InsightLogicProps | undefined) ?? undefined

        const mergedInsight = mergeCachedInsight(
            state.insight ?? existingInsightProps?.cachedInsight,
            cachedResults,
            queryNode
        )

        const doNotLoad = existingInsightProps?.doNotLoad ?? !!mergedInsight
        const dashboardItemId = existingInsightProps?.dashboardItemId ?? 'render-query'

        const insightProps: InsightLogicProps = {
            ...existingInsightProps,
            dashboardItemId,
            cachedInsight: mergedInsight,
            doNotLoad,
            query: queryNode,
        }

        context = { ...context, insightProps }
        cachedResults = mergedInsight ?? cachedResults
        needsResults = !mergedInsight || typeof mergedInsight.result === 'undefined'
    } else {
        needsResults = cachedResults === null || typeof cachedResults === 'undefined'
        if (!needsResults && isPartialInsightModel(cachedResults)) {
            needsResults = typeof cachedResults.result === 'undefined'
        }
    }

    return {
        query,
        cachedResults,
        context,
        needsResults,
    }
}

function mergeCachedInsight(
    candidate: Partial<QueryBasedInsightModel> | null | undefined,
    cachedResults: AnyResponseType | Partial<QueryBasedInsightModel> | null | undefined,
    query: InsightVizNode
): Partial<QueryBasedInsightModel> | undefined {
    const baseInsight =
        candidate ??
        (isPartialInsightModel(cachedResults) ? (cachedResults as Partial<QueryBasedInsightModel>) : undefined)

    const resultValue = extractResult(baseInsight, cachedResults)

    if (!baseInsight && typeof resultValue === 'undefined') {
        return undefined
    }

    const merged: Partial<QueryBasedInsightModel> = {
        ...baseInsight,
        query: (baseInsight?.query as InsightVizNode) ?? query,
    }

    if (typeof resultValue !== 'undefined') {
        merged.result = resultValue
    }

    if (!merged.short_id) {
        merged.short_id = 'render-query'
    }

    if (!('filters' in merged) || merged.filters == null) {
        merged.filters = {}
    }

    return merged
}

function extractResult(
    insight: Partial<QueryBasedInsightModel> | undefined,
    cachedResults: AnyResponseType | Partial<QueryBasedInsightModel> | null | undefined
): AnyResponseType | undefined {
    if (insight && typeof insight.result !== 'undefined') {
        return insight.result
    }

    if (isPartialInsightModel(cachedResults)) {
        return cachedResults.result
    }

    return cachedResults ?? undefined
}

function sanitizePayload(raw: unknown, source: string): SanitizedPayload {
    if (!raw) {
        return EMPTY_PAYLOAD
    }

    if (typeof raw === 'string') {
        const trimmed = raw.trim()
        if (!trimmed) {
            return EMPTY_PAYLOAD
        }
        try {
            return sanitizePayload(JSON.parse(trimmed), source)
        } catch (error) {
            return {
                payload: {},
                messages: [`${source}: Unable to parse string payload - ${(error as Error).message}`],
            }
        }
    }

    if (!isPlainObject(raw)) {
        return EMPTY_PAYLOAD
    }

    const payload: RenderQueryExternalPayload = {}
    const messages: string[] = []

    for (const [rawKey, rawValue] of Object.entries(raw)) {
        if (!SUPPORTED_KEYS.has(rawKey)) {
            continue
        }
        const key = rawKey === 'cached_results' ? 'cachedResults' : (rawKey as keyof RenderQueryExternalPayload)

        const normalized = normalizeValue(rawValue, String(key), source, messages)
        if (normalized !== undefined) {
            ;(payload as any)[key] = normalized
        }
    }

    return { payload, messages }
}

function normalizeValue(value: unknown, key: string, source: string, messages: string[]): unknown {
    if (value === undefined) {
        return undefined
    }

    if (value === null) {
        return null
    }

    if (typeof value === 'string') {
        const trimmed = value.trim()
        if (!trimmed) {
            return null
        }
        try {
            return JSON.parse(trimmed)
        } catch (error) {
            messages.push(`${source}: Unable to parse ${key} - ${(error as Error).message}`)
            return undefined
        }
    }

    return value
}

function extractFromSearch(): SanitizedPayload {
    const params = new URLSearchParams(window.location.search)
    const raw: Record<string, unknown> = {}
    let hasValue = false

    for (const key of ['query', 'cachedResults', 'cached_results', 'context', 'insight']) {
        if (params.has(key)) {
            raw[key] = params.get(key)
            hasValue = true
        }
    }

    return hasValue ? sanitizePayload(raw, 'URL parameters') : EMPTY_PAYLOAD
}

function extractFromHash(): SanitizedPayload {
    const hash = window.location.hash?.replace(/^#/, '') ?? ''
    if (!hash) {
        return EMPTY_PAYLOAD
    }

    if (hash.startsWith('{') || hash.startsWith('[')) {
        return sanitizePayload(hash, 'URL hash')
    }

    try {
        const params = new URLSearchParams(hash)
        const raw: Record<string, unknown> = {}
        let hasValue = false

        for (const key of ['query', 'cachedResults', 'cached_results', 'context', 'insight']) {
            if (params.has(key)) {
                raw[key] = params.get(key)
                hasValue = true
            }
        }

        return hasValue ? sanitizePayload(raw, 'URL hash parameters') : EMPTY_PAYLOAD
    } catch (error) {
        return {
            payload: {},
            messages: [`URL hash: Unable to parse parameters - ${(error as Error).message}`],
        }
    }
}

function extractFromFrameDataset(): SanitizedPayload {
    try {
        const frame = window.frameElement as HTMLIFrameElement | null
        if (!frame) {
            return EMPTY_PAYLOAD
        }
        const { dataset } = frame
        const raw: Record<string, unknown> = {}
        let hasValue = false

        if (dataset.query !== undefined) {
            raw.query = dataset.query
            hasValue = true
        }
        if (dataset.cachedResults !== undefined) {
            raw.cachedResults = dataset.cachedResults
            hasValue = true
        }
        if (dataset.cached_results !== undefined) {
            raw.cached_results = dataset.cached_results
            hasValue = true
        }
        if (dataset.context !== undefined) {
            raw.context = dataset.context
            hasValue = true
        }
        if (dataset.insight !== undefined) {
            raw.insight = dataset.insight
            hasValue = true
        }

        return hasValue ? sanitizePayload(raw, 'iframe dataset') : EMPTY_PAYLOAD
    } catch (error) {
        console.warn('PostHog render query: Unable to read iframe dataset.', error)
        return EMPTY_PAYLOAD
    }
}

function extractFromWindowName(): SanitizedPayload {
    const name = window.name?.trim()
    if (!name) {
        return EMPTY_PAYLOAD
    }

    if (name.startsWith('{') || name.startsWith('[')) {
        return sanitizePayload(name, 'window.name')
    }

    return EMPTY_PAYLOAD
}

function extractPayloadFromMessage(data: unknown): SanitizedPayload | null {
    if (!data) {
        return null
    }

    if (typeof data === 'string') {
        return sanitizePayload(data, 'message')
    }

    if (!isPlainObject(data)) {
        return null
    }

    const type = typeof data.type === 'string' ? data.type : typeof data.event === 'string' ? data.event : null

    if (type === 'posthog:render_query:reset') {
        return {
            payload: { query: null, cachedResults: null, context: null, insight: null },
            messages: [],
        }
    }

    if (type && type !== 'posthog:render_query:update' && type !== 'posthog:render_query:payload') {
        return null
    }

    if ('payload' in data && data.payload) {
        return sanitizePayload(data.payload, 'message payload')
    }

    const hasDirectKeys = Object.keys(data).some((key) => SUPPORTED_KEYS.has(key))
    if (hasDirectKeys) {
        return sanitizePayload(data, 'message')
    }

    return null
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    if (typeof value !== 'object' || value === null) {
        return false
    }

    const prototype = Object.getPrototypeOf(value)
    return prototype === Object.prototype || prototype === null
}

function isPartialInsightModel(value: unknown): value is Partial<QueryBasedInsightModel> {
    if (!isPlainObject(value)) {
        return false
    }

    return 'result' in value || 'query' in value
}
