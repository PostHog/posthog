import './RenderQuery.scss'

import { useEffect, useState } from 'react'

import { useThemedHtml } from 'lib/hooks/useThemedHtml'

import { Query } from '~/queries/Query/Query'
import { AnyResponseType, Node } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { DataColorThemeModel, QueryBasedInsightModel } from '~/types'

interface RenderQueryExternalPayload {
    query?: Node | string | null
    cachedResults?: AnyResponseType | Partial<QueryBasedInsightModel> | null
    context?: QueryContext<any> | null
    insight?: Partial<QueryBasedInsightModel> | null
    themes?: DataColorThemeModel[]
}

interface RenderQueryState extends RenderQueryExternalPayload {
    messages: string[]
}

interface SanitizedPayload {
    payload: RenderQueryExternalPayload
    messages: string[]
}

declare global {
    interface Window {
        POSTHOG_RENDER_QUERY_PAYLOAD?: RenderQueryExternalPayload
    }
}

const EMPTY_PAYLOAD: SanitizedPayload = { payload: {}, messages: [] }
const SUPPORTED_KEYS = new Set(['query', 'cachedResults', 'cached_results', 'context', 'insight'])

export function RenderQueryApp(): JSX.Element {
    const [state, setState] = useState<RenderQueryState>(() => initializeState())

    useThemedHtml(false)

    useEffect(() => {
        const handleMessage = (event: MessageEvent): void => {
            const sanitized = sanitizePayload(event.data, 'postMessage')
            if (!hasSanitizedPayloadData(sanitized)) {
                return
            }
            setState((previous) => applySanitizedPayload(previous, sanitized))
        }

        window.addEventListener('message', handleMessage)
        return () => {
            window.removeEventListener('message', handleMessage)
        }
    }, [setState])

    return (
        <div className="RenderQuery h-full w-full">
            {state.messages.length > 0 && (
                <div className="RenderQuery__messages">
                    {state.messages.map((message, index) => (
                        <div className="RenderQuery__message" key={`${index}-${message}`}>
                            {message}
                        </div>
                    ))}
                </div>
            )}
            {state.cachedResults ? (
                <div className="RenderQuery__content">
                    <Query
                        query={state.query as any}
                        cachedResults={state.cachedResults}
                        readOnly
                        embedded
                        inSharedMode
                        context={state.context ?? undefined}
                    />
                </div>
            ) : (
                <div className="RenderQuery__placeholder">
                    {state.query
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
                next[key] = value as any
            }
        }
    }
    return next
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

function hasSanitizedPayloadData(sanitized: SanitizedPayload): boolean {
    return Object.keys(sanitized.payload).length > 0 || sanitized.messages.length > 0
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    if (typeof value !== 'object' || value === null) {
        return false
    }

    const prototype = Object.getPrototypeOf(value)
    return prototype === Object.prototype || prototype === null
}
