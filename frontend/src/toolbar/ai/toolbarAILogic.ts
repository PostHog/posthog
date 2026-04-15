import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import { uuid } from 'lib/utils'

import { AssistantEventType } from '~/queries/schema/schema-assistant-messages'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { captureElementScreenshot, uploadScreenshot } from '~/toolbar/utils/screenshot'

import { DOMSnapshot, serializeDOM } from './domSerializer'
import type { toolbarAILogicType } from './toolbarAILogicType'
import { streamConversation } from './toolbarStreamClient'

export type ToolbarMessageRole = 'user' | 'assistant'

export interface ToolbarMessage {
    id: string
    role: ToolbarMessageRole
    content: string
    /** True while the assistant is still streaming this message. */
    streaming?: boolean
    /** True if generation errored out partway. */
    error?: boolean
}

export const toolbarAILogic = kea<toolbarAILogicType>([
    path(['toolbar', 'ai', 'toolbarAILogic']),

    actions({
        submitMessage: (content: string) => ({ content }),
        appendUserMessage: (message: ToolbarMessage) => ({ message }),
        appendAssistantMessage: (message: ToolbarMessage) => ({ message }),
        replaceAssistantMessage: (id: string, content: string, opts?: { streaming?: boolean; error?: boolean }) => ({
            id,
            content,
            opts: opts ?? {},
        }),
        markStreamComplete: (id: string) => ({ id }),
        markStreamError: (id: string, errorMessage: string) => ({ id, errorMessage }),
        setIsCapturingContext: (isCapturing: boolean) => ({ isCapturing }),
        setIsStreaming: (isStreaming: boolean) => ({ isStreaming }),
        setError: (error: string | null) => ({ error }),
        setController: (controller: AbortController | null) => ({ controller }),
        cancelStream: true,
        reset: true,
    }),

    reducers({
        messages: [
            [] as ToolbarMessage[],
            {
                appendUserMessage: (state, { message }) => [...state, message],
                appendAssistantMessage: (state, { message }) => [...state, message],
                replaceAssistantMessage: (state, { id, content, opts }) =>
                    state.map((m) =>
                        m.id === id
                            ? {
                                  ...m,
                                  content,
                                  streaming: opts.streaming ?? m.streaming,
                                  error: opts.error ?? m.error,
                              }
                            : m
                    ),
                markStreamComplete: (state, { id }) => state.map((m) => (m.id === id ? { ...m, streaming: false } : m)),
                markStreamError: (state, { id, errorMessage }) =>
                    state.map((m) =>
                        m.id === id
                            ? {
                                  ...m,
                                  streaming: false,
                                  error: true,
                                  content: m.content || errorMessage,
                              }
                            : m
                    ),
                reset: () => [],
            },
        ],
        conversationId: [
            uuid(),
            {
                reset: () => uuid(),
            },
        ],
        isCapturingContext: [
            false,
            {
                setIsCapturingContext: (_, { isCapturing }) => isCapturing,
                reset: () => false,
            },
        ],
        isStreaming: [
            false,
            {
                setIsStreaming: (_, { isStreaming }) => isStreaming,
                reset: () => false,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
                submitMessage: () => null,
                reset: () => null,
            },
        ],
        controller: [
            null as AbortController | null,
            {
                setController: (_, { controller }) => controller,
                reset: () => null,
            },
        ],
    }),

    selectors({
        isBusy: [(s) => [s.isCapturingContext, s.isStreaming], (capturing, streaming) => capturing || streaming],
        canSubmit: [(s) => [s.isBusy], (isBusy: boolean) => !isBusy],
    }),

    listeners(({ actions, values, cache }) => ({
        submitMessage: async ({ content }) => {
            const trimmed = content.trim()
            if (!trimmed || values.isBusy) {
                return
            }

            const traceId = uuid()
            const userMessageId = uuid()
            const assistantMessageId = uuid()

            actions.appendUserMessage({ id: userMessageId, role: 'user', content: trimmed })

            actions.setIsCapturingContext(true)
            let dom: DOMSnapshot
            let screenshotMediaId: string | null = null
            try {
                // Run DOM serialization and screenshot capture in parallel.
                // DOM serialization is synchronous and fast; screenshots are slow
                // and may fail on hostile pages (CORS-tainted images, fonts, etc.) —
                // failure is non-fatal, we just send the DOM snapshot alone.
                const screenshotPromise = captureElementScreenshot(document.documentElement)
                    .then((blob) => uploadScreenshot(blob).then((r) => r.mediaId))
                    .catch((e: unknown) => {
                        captureToolbarException(e, 'toolbar_ai_screenshot')
                        return null
                    })

                dom = serializeDOM()
                screenshotMediaId = await screenshotPromise
            } catch (e) {
                captureToolbarException(e, 'toolbar_ai_context_capture')
                actions.setIsCapturingContext(false)
                actions.setError('Failed to capture page context. Please try again.')
                return
            }
            actions.setIsCapturingContext(false)

            actions.appendAssistantMessage({
                id: assistantMessageId,
                role: 'assistant',
                content: '',
                streaming: true,
            })

            actions.setIsStreaming(true)
            toolbarPosthogJS.capture('toolbar ai message sent', {
                conversation_id: values.conversationId,
                trace_id: traceId,
                has_screenshot: !!screenshotMediaId,
                dom_snapshot_size: dom.tree.length,
            })

            const controller = streamConversation({
                content: trimmed,
                conversationId: values.conversationId,
                traceId,
                contextualTools: {
                    toolbar_context: {
                        page_url: dom.url,
                        page_title: dom.title,
                        viewport: dom.viewport,
                        dom_snapshot: dom.tree,
                        ...(screenshotMediaId ? { screenshot_media_id: screenshotMediaId } : {}),
                    },
                },
                onMessage: ({ event, data }) => {
                    if (event !== AssistantEventType.Message) {
                        return
                    }
                    let parsed: unknown
                    try {
                        parsed = JSON.parse(data)
                    } catch {
                        return
                    }
                    const candidates = Array.isArray(parsed) ? parsed : [parsed]
                    const aiMessages = candidates.filter(
                        (m): m is { type: 'ai'; content: string } =>
                            !!m &&
                            typeof m === 'object' &&
                            (m as any).type === 'ai' &&
                            typeof (m as any).content === 'string'
                    )
                    if (aiMessages.length === 0) {
                        return
                    }
                    const latest = aiMessages[aiMessages.length - 1]
                    actions.replaceAssistantMessage(assistantMessageId, latest.content, { streaming: true })
                },
                onError: (err) => {
                    captureToolbarException(err, 'toolbar_ai_stream')
                    actions.markStreamError(assistantMessageId, 'Sorry, something went wrong. Please try again.')
                    actions.setIsStreaming(false)
                    actions.setController(null)
                    actions.setError(err.message)
                },
                onComplete: () => {
                    actions.markStreamComplete(assistantMessageId)
                    actions.setIsStreaming(false)
                    actions.setController(null)
                    toolbarPosthogJS.capture('toolbar ai message completed', {
                        conversation_id: values.conversationId,
                        trace_id: traceId,
                    })
                },
            })

            actions.setController(controller)
            cache.activeStreamId = assistantMessageId
        },
        cancelStream: () => {
            values.controller?.abort()
            actions.setController(null)
            actions.setIsStreaming(false)
            const id = cache.activeStreamId as string | undefined
            if (id) {
                actions.markStreamComplete(id)
            }
            toolbarPosthogJS.capture('toolbar ai message cancelled', {
                conversation_id: values.conversationId,
            })
        },
        reset: () => {
            values.controller?.abort()
        },
    })),

    afterMount(({ actions, cache }) => {
        // Reset the conversation when the user navigates within the SPA so we don't
        // mix DOM contexts from different pages in a single thread.
        cache.lastPathname = window.location.pathname
        cache.disposables.add(() => {
            const onNavigation = (): void => {
                if (cache.lastPathname && cache.lastPathname !== window.location.pathname) {
                    actions.reset()
                }
                cache.lastPathname = window.location.pathname
            }
            window.addEventListener('popstate', onNavigation)
            return () => window.removeEventListener('popstate', onNavigation)
        }, 'navigationListener')
    }),
])
