import { EventSourceMessage } from '@microsoft/fetch-event-source'
import { getVersion, receiveTransaction } from '@tiptap/pm/collab'
import { Step } from '@tiptap/pm/transform'
import { actions, beforeUnmount, kea, key, listeners, path, props, reducers } from 'kea'

const RECONNECT_DELAY_MS = 1000
import posthog from 'posthog-js'

import api from 'lib/api'
import { JSONContent, TTEditor } from 'lib/components/RichContentEditor/types'
import { uuid } from 'lib/utils'

import type { notebookCollabLogicType } from './notebookCollabLogicType'
import { ClientPresence, REMOTE_PRESENCE_META } from './RemotePresenceExtension'

/** SSE `event: step` body from the collab stream endpoint */
type StreamStepEvent = {
    step: Record<string, any>
    client_id: string
    user_id: number
    user_name: string
    cursor_head: number
}

/** Presence fields piggybacked on every SSE step event (`cursor_head` → `head`) */
export type RemotePresence = {
    userId: number
    userName: string
    head: number
}

export type RemoteStep = {
    step: Record<string, any>
    clientId: string
    /** Resulting version after this step is applied (== local getVersion + 1 in normal flow) */
    version: number
    presence?: RemotePresence
}

/**
 * Idempotent step apply. The same step may arrive via SSE *and* via the 409
 * conflict body on a concurrent save; whichever lands first wins, the second
 * skips by version. Presence is always propagated so the caret stays in sync.
 * Throws if the step itself can't be applied — caller decides how to surface it.
 */
export function applyRemoteStep(editor: TTEditor, remote: RemoteStep): void {
    const expected = getVersion(editor.state) + 1

    const presenceMeta = (): ClientPresence | null => {
        if (!remote.presence) {
            return null
        }
        return { clientId: remote.clientId, ...remote.presence, lastSeenAt: Date.now() }
    }

    if (remote.version < expected) {
        // Already applied via the other channel - still update presence so the caret tracks typing
        const meta = presenceMeta()
        if (meta) {
            editor.view.dispatch(editor.state.tr.setMeta(REMOTE_PRESENCE_META, meta))
        }
        return
    }

    if (remote.version > expected) {
        // Out-of-order; the next save's 409 carries the missed range, or 410 → reload
        return
    }

    const step = Step.fromJSON(editor.state.schema, remote.step)
    let tr = receiveTransaction(editor.state, [step], [remote.clientId], {
        mapSelectionBackward: true,
    })
    const meta = presenceMeta()
    if (meta) {
        tr = tr.setMeta(REMOTE_PRESENCE_META, meta)
    }
    editor.view.dispatch(tr)
}

export const notebookCollabLogic = kea<notebookCollabLogicType>([
    props({} as { shortId: string }),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookCollabLogic', key]),
    key(({ shortId }) => shortId),

    actions({
        bindEditor: (editor: TTEditor) => ({ editor }),
        unbindEditor: true,
        /** Ack our own saved steps so PM-collab advances its version (matching clientID = no-op apply). */
        ackLocalSteps: (steps: Record<string, any>[], clientID: string) => ({ steps, clientID }),
        /** Apply steps received from SSE or a 409 body. Idempotent by version. */
        applyRemoteSteps: (steps: RemoteStep[]) => ({ steps }),
        /** Bubbles up to notebookLogic when receiveTransaction throws — the conflict modal opens. */
        rebaseFailed: (params: { localContent: JSONContent; localText: string }) => params,
        connectStream: true,
        disconnectStream: true,
        streamOpened: true,
        streamClosed: (error: string | null = null) => ({ error }),
    }),

    reducers({
        ttEditor: [
            null as TTEditor | null,
            {
                bindEditor: (_, { editor }) => editor,
                unbindEditor: () => null,
            },
        ],
        // Stable per-logic clientID; shared with the PM collab plugin for self-event filtering.
        clientID: [uuid() as string, {}],
        // Optimistic: true while the SSE await is in flight. Flips false on close/error so
        // the UI can show a "live updates paused" indicator during the brief reconnect gap.
        streamConnected: [
            false,
            {
                streamOpened: () => true,
                streamClosed: () => false,
                disconnectStream: () => false,
            },
        ],
        streamError: [
            null as string | null,
            {
                streamOpened: () => null,
                streamClosed: (_, { error }) => error,
                disconnectStream: () => null,
            },
        ],
    }),

    listeners(({ actions, values, props, cache }) => ({
        bindEditor: () => {
            actions.connectStream()
        },

        unbindEditor: () => {
            actions.disconnectStream()
        },

        ackLocalSteps: ({ steps, clientID }) => {
            const editor = values.ttEditor
            if (!editor || editor.isDestroyed || !steps.length) {
                return
            }
            try {
                const parsed = steps.map((s: Record<string, any>) => Step.fromJSON(editor.state.schema, s))
                const tr = receiveTransaction(
                    editor.state,
                    parsed,
                    parsed.map(() => clientID),
                    {
                        mapSelectionBackward: true,
                    }
                )
                editor.view.dispatch(tr)
            } catch (e) {
                posthog.captureException(e as Error, { action: 'notebook collab ack local steps' })
            }
        },

        applyRemoteSteps: ({ steps }) => {
            const editor = values.ttEditor
            if (!editor || editor.isDestroyed) {
                return
            }
            const localContent = editor.getJSON()
            const localText = editor.getText()
            for (const remote of steps) {
                if (remote.clientId === values.clientID) {
                    continue
                }
                try {
                    applyRemoteStep(editor, remote)
                } catch (e) {
                    posthog.captureException(e as Error, { action: 'notebook collab apply remote step' })
                    actions.rebaseFailed({ localContent, localText })
                    return
                }
            }
        },

        connectStream: async () => {
            cache.abortController?.abort()
            cache.disposables.dispose('reconnectTimer')
            const controller = new AbortController()
            cache.abortController = controller

            const onMessage = (msg: EventSourceMessage): void => {
                if (msg.event !== 'step' || !msg.data) {
                    return
                }
                // SSE id is the Redis stream id `N-0` and N is the prosemirror version.
                // We use it for both reconnection (Last-Event-ID) and idempotency.
                cache.lastEventId = msg.id
                const version = parseInt(msg.id.split('-', 1)[0], 10)
                if (!Number.isFinite(version)) {
                    return
                }
                let parsed: StreamStepEvent
                try {
                    parsed = JSON.parse(msg.data) as StreamStepEvent
                } catch (e) {
                    posthog.captureException(e as Error, { action: 'notebook collab stream parse' })
                    return
                }
                if (parsed.client_id === values.clientID) {
                    return
                }
                const editor = values.ttEditor
                if (!editor || editor.isDestroyed) {
                    return
                }
                const localContent = editor.getJSON()
                const localText = editor.getText()
                try {
                    applyRemoteStep(editor, {
                        step: parsed.step,
                        clientId: parsed.client_id,
                        version,
                        presence: {
                            userId: parsed.user_id,
                            userName: parsed.user_name,
                            head: parsed.cursor_head,
                        },
                    })
                } catch (e) {
                    posthog.captureException(e as Error, { action: 'notebook collab apply remote step' })
                    actions.rebaseFailed({ localContent, localText })
                }
            }

            const onError = (error: any): void => {
                if (controller.signal.aborted) {
                    return
                }
                const message = error instanceof Error ? error.message : String(error)
                actions.streamClosed(message)
                posthog.captureException(error instanceof Error ? error : new Error(message), {
                    action: 'notebook collab stream',
                })
            }

            // The await runs for the connection's lifetime. fetch-event-source retries
            // internal errors on its own, but resolves silently when the server closes the
            // body cleanly — which the backend does every STREAM_LIFETIME_SECONDS (5 min)
            // by design. We have to schedule the reconnect ourselves, passing the last
            // seen event id so the resumed stream picks up where this one left off.
            // onOpen fires on every successful fetch — including fetch-event-source's
            // internal retries — so the UI flips back to "live" once we're reconnected.
            const onOpen = (): void => {
                if (controller.signal.aborted) {
                    return
                }
                actions.streamOpened()
            }
            try {
                await api.notebooks.collabStream(props.shortId, {
                    onMessage,
                    onError,
                    onOpen,
                    signal: controller.signal,
                    lastEventId: cache.lastEventId,
                })
            } catch (e) {
                if (controller.signal.aborted) {
                    return
                }
                actions.streamClosed(e instanceof Error ? e.message : String(e))
                posthog.captureException(e as Error, { action: 'notebook collab stream open' })
            }

            if (controller.signal.aborted) {
                return
            }

            actions.streamClosed()

            // pauseOnPageHidden: false so a server-side lifetime cap that hits while the tab
            // is backgrounded still triggers a reconnect — the underlying SSE uses
            // openWhenHidden: true and is expected to stay live regardless of visibility.
            cache.disposables.add(
                () => {
                    const id = window.setTimeout(() => actions.connectStream(), RECONNECT_DELAY_MS)
                    return () => window.clearTimeout(id)
                },
                'reconnectTimer',
                { pauseOnPageHidden: false }
            )
        },

        disconnectStream: () => {
            cache.abortController?.abort()
            cache.abortController = null
            cache.disposables.dispose('reconnectTimer')
        },
    })),

    beforeUnmount(({ actions }) => {
        actions.disconnectStream()
        actions.unbindEditor()
    }),
])
