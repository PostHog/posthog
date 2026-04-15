import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { uuid } from 'lib/utils'

import {
    AssistantEventType,
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCall,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
    PlanningMessage,
    ReasoningMessage,
} from '~/queries/schema/schema-assistant-messages'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { captureElementScreenshot, uploadScreenshot } from '~/toolbar/utils/screenshot'

import { DOMSnapshot, serializeDOM } from './domSerializer'
import type { toolbarAILogicType } from './toolbarAILogicType'
import { streamConversation } from './toolbarStreamClient'

/** Status of a single thread item as it streams in from the server. */
export type ThreadItemStatus = 'loading' | 'completed' | 'error'

/**
 * Server-originated message we know how to render in the toolbar. Mirrors the
 * main app's `ThreadMessage`, scoped to the types we display: human turn,
 * assistant reply (incl. tool_calls), reasoning/"Thought", planning, failure,
 * and the tool-result messages we consume inline under their parent.
 */
export type ThreadItemMessage =
    | HumanMessage
    | AssistantMessage
    | ReasoningMessage
    | FailureMessage
    | PlanningMessage
    | AssistantToolCallMessage
export type ThreadItem = ThreadItemMessage & { status: ThreadItemStatus }

/** Server IDs starting with `temp-` indicate the message is still streaming. */
function isLoadingId(id: string | undefined | null): boolean {
    return !id || id.startsWith('temp-')
}

/** Tool-call execution status as shown in the UI. */
export type ToolCallStatus = 'in_progress' | 'completed' | 'failed'

/**
 * A tool call augmented with the status we derived by looking forward in the
 * thread for a matching `AssistantToolCallMessage` by `tool_call_id`.
 */
export interface EnhancedToolCall extends AssistantToolCall {
    status: ToolCallStatus
    result?: AssistantToolCallMessage
}

/**
 * A single renderable row in the chat. For assistant messages with tool_calls
 * we attach `enhancedToolCalls` so the renderer can show tool-call rows with
 * status chips without re-computing the join each render.
 */
export type ViewItem = ThreadItem & { enhancedToolCalls?: EnhancedToolCall[] }

export interface SelectedElementContext {
    /** CSS selector computed by the toolbar's selector-quality heuristic. */
    selector: string | null
    tagName: string
    /** First ~200 chars of visible text content. */
    textPreview: string
    /** First ~2000 chars of outerHTML, used for precise element context. */
    outerHtmlPreview: string
    /** Stable-ish attributes (id, class, role, aria-*, data-*) for identification. */
    attributes: Record<string, string>
}

const OUTER_HTML_MAX = 2000
const TEXT_PREVIEW_MAX = 200
const ATTR_VALUE_MAX = 200
const RELEVANT_ATTR_NAMES = new Set(['id', 'class', 'role', 'href', 'type', 'name', 'title', 'alt'])

export const toolbarAILogic = kea<toolbarAILogicType>([
    path(['toolbar', 'ai', 'toolbarAILogic']),

    connect(() => ({
        values: [elementsLogic, ['selectedElementMeta']],
        actions: [
            elementsLogic,
            ['enableInspect', 'disableInspect', 'setSelectedElement', 'setHoverElement'],
            toolbarLogic,
            ['setIsBlurred'],
        ],
    })),

    actions({
        submitMessage: (content: string) => ({ content }),
        /** Append a thread item (user/assistant/reasoning/failure). */
        addThreadItem: (item: ThreadItem) => ({ item }),
        /** Replace the thread item at `index`. Used when the server re-emits a message with the same id. */
        replaceThreadItem: (index: number, item: ThreadItem) => ({ index, item }),
        /** Remove any thread items still in `loading` state — used on stream end/error. */
        finalizeStreamingItems: true,
        /** Append a one-off failure item so the user sees a surfaced error. */
        appendFailureMessage: (content: string) => ({ content }),
        setIsCapturingContext: (isCapturing: boolean) => ({ isCapturing }),
        setIsStreaming: (isStreaming: boolean) => ({ isStreaming }),
        setError: (error: string | null) => ({ error }),
        setController: (controller: AbortController | null) => ({ controller }),
        startElementPick: true,
        cancelElementPick: true,
        setSelectedElementContext: (context: SelectedElementContext) => ({ context }),
        clearSelectedElementContext: true,
        cancelStream: true,
        reset: true,
    }),

    reducers({
        thread: [
            [] as ThreadItem[],
            {
                addThreadItem: (state, { item }) => [...state, item],
                replaceThreadItem: (state, { index, item }) =>
                    state.map((existing, i) => (i === index ? item : existing)),
                finalizeStreamingItems: (state) =>
                    state.map((item) => (item.status === 'loading' ? { ...item, status: 'completed' } : item)),
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
        pickMode: [
            false,
            {
                startElementPick: () => true,
                cancelElementPick: () => false,
                setSelectedElementContext: () => false,
                reset: () => false,
            },
        ],
        selectedElementContext: [
            null as SelectedElementContext | null,
            {
                setSelectedElementContext: (_, { context }) => context,
                clearSelectedElementContext: () => null,
                reset: () => null,
            },
        ],
    }),

    selectors({
        isBusy: [(s) => [s.isCapturingContext, s.isStreaming], (capturing, streaming) => capturing || streaming],
        canSubmit: [(s) => [s.isBusy], (isBusy: boolean) => !isBusy],
        /**
         * The user-facing view of the thread: empty assistant messages are
         * dropped, tool-result messages are folded into their parent assistant
         * message's `tool_calls`, and each tool_call gets a derived
         * `status`+`result`. Mirrors the main app's `threadGrouped` selector
         * (see frontend/src/scenes/max/maxThreadLogic.tsx `enhanceThreadToolCalls`).
         */
        viewItems: [
            (s) => [s.thread, s.isStreaming],
            (thread: ThreadItem[], isStreaming: boolean): ViewItem[] => {
                const toolResults = new Map<string, AssistantToolCallMessage>()
                for (const item of thread) {
                    if (item.type === AssistantMessageType.ToolCall && (item as any).tool_call_id) {
                        toolResults.set((item as AssistantToolCallMessage).tool_call_id, item)
                    }
                }

                const result: ViewItem[] = []
                for (const item of thread) {
                    if (item.type === AssistantMessageType.ToolCall) {
                        // Consumed inline under the parent assistant message
                        continue
                    }

                    if (item.type === AssistantMessageType.Assistant) {
                        const assistant = item
                        const hasContent = !!assistant.content
                        const hasToolCalls = !!assistant.tool_calls?.length
                        if (!hasContent && !hasToolCalls) {
                            // Empty placeholder assistant turn — skip so we don't
                            // render a blank bubble while streaming.
                            continue
                        }
                        if (hasToolCalls) {
                            const enhancedToolCalls: EnhancedToolCall[] = assistant.tool_calls!.map((tc) => {
                                const toolResult = toolResults.get(tc.id)
                                if (toolResult) {
                                    return { ...tc, status: 'completed', result: toolResult }
                                }
                                // Still streaming if the overall stream is active,
                                // otherwise assume the tool never completed.
                                return { ...tc, status: isStreaming ? 'in_progress' : 'failed' }
                            })
                            result.push({ ...assistant, enhancedToolCalls })
                            continue
                        }
                    }

                    result.push(item)
                }
                return result
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        submitMessage: async ({ content }) => {
            const trimmed = content.trim()
            if (!trimmed || values.isBusy) {
                return
            }

            const traceId = uuid()

            // Provisional local human bubble — the backend will re-emit a matching
            // `human` message with the same trace_id, at which point we replace it.
            actions.addThreadItem({
                type: AssistantMessageType.Human,
                id: `local-${uuid()}`,
                content: trimmed,
                trace_id: traceId,
                status: 'completed',
            })

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

            actions.setIsStreaming(true)
            toolbarPosthogJS.capture('toolbar ai message sent', {
                conversation_id: values.conversationId,
                trace_id: traceId,
                has_screenshot: !!screenshotMediaId,
                dom_snapshot_size: dom.tree.length,
            })

            const selectedElement = values.selectedElementContext
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
                        ...(selectedElement
                            ? {
                                  selected_element: {
                                      selector: selectedElement.selector,
                                      tag_name: selectedElement.tagName,
                                      text_preview: selectedElement.textPreview,
                                      outer_html_preview: selectedElement.outerHtmlPreview,
                                      attributes: selectedElement.attributes,
                                  },
                              }
                            : {}),
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
                    for (const raw of candidates) {
                        handleStreamedMessage(raw, {
                            addThreadItem: actions.addThreadItem,
                            replaceThreadItem: actions.replaceThreadItem,
                            getThread: () => values.thread,
                            traceId,
                        })
                    }
                },
                onError: (err) => {
                    captureToolbarException(err, 'toolbar_ai_stream')
                    actions.finalizeStreamingItems()
                    actions.appendFailureMessage('Sorry, something went wrong. Please try again.')
                    actions.setIsStreaming(false)
                    actions.setController(null)
                    actions.setError(err.message)
                },
                onComplete: () => {
                    actions.finalizeStreamingItems()
                    actions.setIsStreaming(false)
                    actions.setController(null)
                    toolbarPosthogJS.capture('toolbar ai message completed', {
                        conversation_id: values.conversationId,
                        trace_id: traceId,
                    })
                },
            })

            actions.setController(controller)
            cache.activeTraceId = traceId
        },
        cancelStream: () => {
            values.controller?.abort()
            actions.setController(null)
            actions.setIsStreaming(false)
            actions.finalizeStreamingItems()
            toolbarPosthogJS.capture('toolbar ai message cancelled', {
                conversation_id: values.conversationId,
            })
        },
        appendFailureMessage: ({ content }) => {
            actions.addThreadItem({
                type: AssistantMessageType.Failure,
                id: `local-failure-${uuid()}`,
                content,
                status: 'error',
            })
        },
        startElementPick: () => {
            // Turn on the element-picking overlay without switching `visibleMenu`
            // so the AI panel stays mounted. The panel will blur when the user
            // clicks the page, and unblur again after we capture the element.
            actions.enableInspect()
            toolbarPosthogJS.capture('toolbar ai element pick started', {
                conversation_id: values.conversationId,
            })
        },
        cancelElementPick: () => {
            actions.setHoverElement(null)
            actions.setSelectedElement(null)
            actions.disableInspect()
        },
        [elementsLogic.actionTypes.setSelectedElement]: ({ element }: { element: HTMLElement | null }) => {
            if (!values.pickMode || !element) {
                return
            }
            const meta = values.selectedElementMeta
            const selector = meta?.actionStep?.selector ?? null
            const tagName = element.tagName.toLowerCase()
            const textPreview = (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, TEXT_PREVIEW_MAX)
            const attributes: Record<string, string> = {}
            for (let i = 0; i < element.attributes.length; i++) {
                const attr = element.attributes[i]
                const name = attr.name
                if (RELEVANT_ATTR_NAMES.has(name) || name.startsWith('data-') || name.startsWith('aria-')) {
                    attributes[name] = attr.value.slice(0, ATTR_VALUE_MAX)
                }
            }
            const outerHtmlPreview = element.outerHTML.slice(0, OUTER_HTML_MAX)
            actions.setSelectedElementContext({ selector, tagName, textPreview, outerHtmlPreview, attributes })
            // Exit inspect mode after a single pick.
            actions.setHoverElement(null)
            actions.setSelectedElement(null)
            actions.disableInspect()
            // Clicking the page blurred the toolbar menu — bring it back so the
            // user sees the chip immediately without having to hover the bar.
            actions.setIsBlurred(false)
            toolbarPosthogJS.capture('toolbar ai element picked', {
                conversation_id: values.conversationId,
                tag: tagName,
                has_selector: !!selector,
            })
        },
        reset: () => {
            values.controller?.abort()
            if (values.pickMode) {
                actions.disableInspect()
            }
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

const DISPLAYABLE_TYPES = new Set<string>([
    AssistantMessageType.Human,
    AssistantMessageType.Assistant,
    AssistantMessageType.Reasoning,
    AssistantMessageType.Failure,
    AssistantMessageType.Planning,
    // Stored in the thread so we can join results into the matching tool_call
    // row, then hidden from `viewItems` itself.
    AssistantMessageType.ToolCall,
])

interface StreamHandlerContext {
    addThreadItem: (item: ThreadItem) => void
    replaceThreadItem: (index: number, item: ThreadItem) => void
    getThread: () => ThreadItem[]
    traceId: string
}

/**
 * Dispatch a single streamed message into the thread, mirroring the main app:
 *  - messages are keyed by server `id`: replace-by-id when one already exists
 *  - a `human` message coming back from the server replaces our provisional
 *    local bubble (matched by `trace_id`)
 *  - unsupported types (visualization, planning, artifact, ...) are ignored
 *    because the toolbar can't render them meaningfully
 */
function handleStreamedMessage(raw: unknown, ctx: StreamHandlerContext): void {
    if (!raw || typeof raw !== 'object') {
        return
    }
    const message = raw as Partial<ThreadItemMessage> & { type?: string; id?: string; trace_id?: string }
    if (!message.type || !DISPLAYABLE_TYPES.has(message.type)) {
        return
    }

    const thread = ctx.getThread()
    const status: ThreadItemStatus = isLoadingId(message.id) ? 'loading' : 'completed'
    const item = { ...message, status } as ThreadItem

    // Backend re-emits the user's human turn; replace our provisional bubble.
    if (message.type === AssistantMessageType.Human && message.trace_id) {
        const localIdx = thread.findIndex(
            (existing) =>
                existing.type === AssistantMessageType.Human &&
                existing.id?.startsWith('local-') &&
                (existing as HumanMessage).trace_id === message.trace_id
        )
        if (localIdx >= 0) {
            ctx.replaceThreadItem(localIdx, { ...item, status: 'completed' })
            return
        }
    }

    if (message.id) {
        const existingIdx = thread.findIndex((existing) => existing.id === message.id)
        if (existingIdx >= 0) {
            ctx.replaceThreadItem(existingIdx, item)
            return
        }
    }

    ctx.addThreadItem(item)
}
