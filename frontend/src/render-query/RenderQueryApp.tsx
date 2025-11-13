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

interface ParsedPayload {
    payload: Partial<RenderQueryExternalPayload>
    messages: string[]
}

declare global {
    interface Window {
        POSTHOG_RENDER_QUERY_PAYLOAD?: RenderQueryExternalPayload
    }
}

const EMPTY_PAYLOAD: ParsedPayload = { payload: {}, messages: [] }
const RAW_PAYLOAD_KEYS = ['query', 'cachedResults', 'cached_results', 'context', 'insight'] as const
const PAYLOAD_KEYS = ['query', 'cachedResults', 'context', 'insight'] as const

export function RenderQueryApp(): JSX.Element {
    const [state, setState] = useState<RenderQueryState>(() => initializeState())
    const [showPlaceholder, setShowPlaceholder] = useState(false)

    useThemedHtml(false)

    useEffect(() => {
        const handleMessage = (event: MessageEvent): void => {
            const parsed = parsePayload(event.data, 'postMessage')
            if (!hasParsedPayloadData(parsed)) {
                return
            }
            setState((previous) => applyParsedPayload(previous, parsed))
        }

        window.addEventListener('message', handleMessage)
        return () => {
            window.removeEventListener('message', handleMessage)
        }
    }, [setState])

    useEffect(() => {
        setShowPlaceholder(false)
        if (state.cachedResults) {
            return
        }
        const timeout = window.setTimeout(() => {
            setShowPlaceholder(true)
        }, 1000)
        return () => {
            window.clearTimeout(timeout)
        }
    }, [state.cachedResults, state.query])

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
                showPlaceholder && (
                    <div className="RenderQuery__placeholder">
                        {state.query
                            ? 'Waiting for cached results. Send cachedResults via postMessage to display data.'
                            : 'No query provided. Send a query via postMessage or include it in the iframe URL.'}
                    </div>
                )
            )}
        </div>
    )
}

function initializeState(): RenderQueryState {
    return [
        parsePayload(window.POSTHOG_RENDER_QUERY_PAYLOAD, 'initial payload'),
        extractFromSearch(),
        extractFromHash(),
        extractFromFrameDataset(),
    ].reduce<RenderQueryState>(applyParsedPayload, {
        query: null,
        cachedResults: null,
        context: null,
        insight: null,
        messages: [],
    })
}

function applyParsedPayload(previous: RenderQueryState, parsed: ParsedPayload): RenderQueryState {
    const { payload, messages } = parsed
    const hasPayload = Object.keys(payload).length > 0
    if (!hasPayload && messages.length === 0) {
        return previous
    }

    const next: RenderQueryState = { ...previous }

    for (const key of PAYLOAD_KEYS) {
        if (Object.prototype.hasOwnProperty.call(payload, key)) {
            const value = payload[key]
            if (value !== undefined) {
                next[key] = value as any
            }
        }
    }

    if (messages.length > 0) {
        next.messages = [...next.messages, ...messages]
    }

    return next
}

function parsePayload(raw: unknown, source: string): ParsedPayload {
    if (!raw) {
        return EMPTY_PAYLOAD
    }

    if (typeof raw === 'string') {
        const trimmed = raw.trim()
        if (!trimmed) {
            return EMPTY_PAYLOAD
        }
        try {
            return parsePayload(JSON.parse(trimmed), source)
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

    const payload: Partial<RenderQueryExternalPayload> = {}
    const messages: string[] = []

    for (const [rawKey, rawValue] of Object.entries(raw)) {
        if (!RAW_PAYLOAD_KEYS.includes(rawKey as (typeof RAW_PAYLOAD_KEYS)[number])) {
            continue
        }
        const key = rawKey === 'cached_results' ? 'cachedResults' : (rawKey as keyof RenderQueryExternalPayload)

        const normalized = normalizeValue(rawValue, String(key), source, messages)
        if (normalized !== undefined) {
            payload[key] = normalized as any
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

function extractFromSearch(): ParsedPayload {
    const params = new URLSearchParams(window.location.search)
    return parsePayload(extractFromParams(params), 'URL parameters')
}

function extractFromHash(): ParsedPayload {
    const hash = window.location.hash?.replace(/^#/, '') ?? ''
    if (!hash) {
        return EMPTY_PAYLOAD
    }

    if (hash.startsWith('{') || hash.startsWith('[')) {
        return parsePayload(hash, 'URL hash')
    }

    try {
        const params = new URLSearchParams(hash)
        return parsePayload(extractFromParams(params), 'URL hash parameters')
    } catch (error) {
        return {
            payload: {},
            messages: [`URL hash: Unable to parse parameters - ${(error as Error).message}`],
        }
    }
}

function extractFromFrameDataset(): ParsedPayload {
    try {
        const frame = window.frameElement as HTMLIFrameElement | null
        if (!frame) {
            return EMPTY_PAYLOAD
        }
        const { dataset } = frame
        const raw: Record<string, unknown> = {}

        for (const key of RAW_PAYLOAD_KEYS) {
            const value = (dataset as Record<string, string | undefined>)[key]
            if (value !== undefined) {
                raw[key] = value
            }
        }

        return Object.keys(raw).length ? parsePayload(raw, 'iframe dataset') : EMPTY_PAYLOAD
    } catch (error) {
        console.warn('PostHog render query: Unable to read iframe dataset.', error)
        return EMPTY_PAYLOAD
    }
}

function extractFromParams(params: URLSearchParams): Record<string, unknown> | null {
    const rawEntries = RAW_PAYLOAD_KEYS.map((key) => {
        const value = params.get(key)
        return value === null ? null : [key, value]
    }).filter((entry): entry is [string, string] => entry !== null)

    return rawEntries.length > 0 ? Object.fromEntries(rawEntries) : null
}

function hasParsedPayloadData(parsed: ParsedPayload): boolean {
    return Object.keys(parsed.payload).length > 0 || parsed.messages.length > 0
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    if (typeof value !== 'object' || value === null) {
        return false
    }

    const prototype = Object.getPrototypeOf(value)
    return prototype === Object.prototype || prototype === null
}
