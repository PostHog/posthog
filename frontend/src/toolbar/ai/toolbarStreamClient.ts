import { createParser } from 'eventsource-parser'

import { AssistantEventType } from '~/queries/schema/schema-assistant-messages'
import { withTokenRefresh } from '~/toolbar/toolbarAuth'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarLogger } from '~/toolbar/toolbarLogger'

export interface ToolbarStreamMessage {
    /** SSE event name. Empty string means a default 'message' event. */
    event: AssistantEventType | string
    /** Raw data payload (typically JSON). */
    data: string
}

export interface ToolbarStreamOptions {
    /** The user message content. */
    content: string
    /** Conversation UUID — generated on first message. */
    conversationId: string
    /** Trace UUID for this turn. */
    traceId: string
    /** Optional contextual tools / extra context dict (e.g. toolbar_context). */
    contextualTools?: Record<string, unknown>
    /** Optional UI context dict — passed straight through to the backend. */
    uiContext?: Record<string, unknown>
    /** Called for each parsed SSE event. */
    onMessage: (event: ToolbarStreamMessage) => void
    /** Called once if the stream errors out (network / auth / server). */
    onError: (error: Error) => void
    /** Called once after the stream cleanly completes. */
    onComplete: () => void
}

const CONVERSATION_PATH = '/api/environments/@current/conversations/'

/**
 * Lightweight SSE client for the Max AI conversation endpoint, using the toolbar's
 * Bearer-token auth (instead of session cookies as the main app does).
 *
 * Returns an AbortController whose `.abort()` cancels the in-flight stream.
 */
export function streamConversation(options: ToolbarStreamOptions): AbortController {
    const controller = new AbortController()

    void runStream(options, controller).catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') {
            return
        }
        const error = err instanceof Error ? err : new Error(String(err))
        toolbarLogger.error('ai', 'Toolbar AI stream failed', { message: error.message })
        options.onError(error)
    })

    return controller
}

async function runStream(options: ToolbarStreamOptions, controller: AbortController): Promise<void> {
    const logic = toolbarConfigLogic.findMounted()
    const accessToken = logic?.values.accessToken
    const uiHost = logic?.values.uiHost

    if (!accessToken || !uiHost) {
        throw new Error('Toolbar not authenticated')
    }

    const url = `${uiHost}${CONVERSATION_PATH}`
    const body = JSON.stringify({
        content: options.content,
        conversation: options.conversationId,
        trace_id: options.traceId,
        contextual_tools: options.contextualTools,
        ui_context: options.uiContext,
    })

    const doFetch = (token: string): Promise<Response> =>
        fetch(url, {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${token}`,
                'Content-Type': 'application/json',
                Accept: 'text/event-stream',
            },
            body,
            signal: controller.signal,
        })

    let response = await doFetch(accessToken)
    response = await withTokenRefresh(response, doFetch)

    if (!response.ok) {
        const text = await response.text().catch(() => '')
        throw new Error(`Toolbar AI stream failed: HTTP ${response.status} ${text.slice(0, 200)}`)
    }
    if (!response.body) {
        throw new Error('Toolbar AI stream returned no body')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    const parser = createParser({
        onEvent: ({ data, event }) => {
            options.onMessage({ event: (event as string) || '', data })
        },
    })

    try {
        for (;;) {
            const { done, value } = await reader.read()
            if (value) {
                parser.feed(decoder.decode(value, { stream: !done }))
            }
            if (done) {
                break
            }
        }
        options.onComplete()
    } finally {
        try {
            reader.releaseLock()
        } catch {
            // Already released by an earlier abort
        }
    }
}
