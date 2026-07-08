import { EventSourceMessage } from '@microsoft/fetch-event-source'
import { getVersion, receiveTransaction, sendableSteps } from '@tiptap/pm/collab'
import { Step } from '@tiptap/pm/transform'
import { actions, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { JSONContent, TTEditor } from 'lib/components/RichContentEditor/types'
import { uuid } from 'lib/utils/dom'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { notebooksCollabPresenceCreate } from 'products/notebooks/frontend/generated/api'

import type { notebookCollabLogicType } from './notebookCollabLogicType'
import {
    getNotebookRemoteParticipants,
    type NotebookRemoteParticipant,
    pruneNotebookRemotePresence,
} from './notebookPresence'
import { ClientPresence, REMOTE_PRESENCE_META } from './RemotePresenceExtension'

const PRESENCE_TTL_MS = 30_000
const PRESENCE_PRUNE_INTERVAL_MS = 5_000
const PRESENCE_HEARTBEAT_MS = 10_000
const PRESENCE_PUBLISH_DEBOUNCE_MS = 250

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
        /** Broadcast the local caret so it moves for others even without typing. */
        publishPresence: true,
        handleRemotePresence: (presence: ClientPresence) => ({ presence }),
        pruneRemotePresence: (now: number = Date.now()) => ({ now }),
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
        streamConnected: [
            false,
            {
                streamOpened: () => true,
                streamClosed: () => false,
                disconnectStream: () => false,
            },
        ],
        isConnecting: [
            false,
            {
                connectStream: () => true,
                streamOpened: () => false,
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
        remotePresence: [
            {} as Record<string, ClientPresence>,
            {
                handleRemotePresence: (state, { presence }) => ({ ...state, [presence.clientId]: presence }),
                pruneRemotePresence: (state, { now }) => pruneNotebookRemotePresence(state, now, PRESENCE_TTL_MS),
                unbindEditor: () => ({}),
            },
        ],
    }),

    selectors({
        remoteParticipants: [
            (s) => [s.remotePresence],
            (remotePresence): NotebookRemoteParticipant[] => getNotebookRemoteParticipants(remotePresence),
        ],
    }),

    listeners(({ actions, values, props, cache }) => ({
        bindEditor: ({ editor }) => {
            actions.connectStream()
            actions.publishPresence()

            cache.disposables.add(() => {
                const onSelectionUpdate = (): void => actions.publishPresence()
                editor.on('selectionUpdate', onSelectionUpdate)
                return () => {
                    editor.off('selectionUpdate', onSelectionUpdate)
                }
            }, 'presenceSelectionUpdate')

            // Re-announce the caret while idle so it outlives the receivers' TTL. Pausing on
            // hidden tabs is deliberate: backgrounded editors' carets fade out remotely.
            cache.disposables.add(() => {
                const intervalId = window.setInterval(() => actions.publishPresence(), PRESENCE_HEARTBEAT_MS)
                return () => window.clearInterval(intervalId)
            }, 'presenceHeartbeat')

            cache.disposables.add(() => {
                const intervalId = window.setInterval(() => actions.pruneRemotePresence(), PRESENCE_PRUNE_INTERVAL_MS)
                return () => window.clearInterval(intervalId)
            }, 'presencePrune')
        },

        unbindEditor: () => {
            actions.disconnectStream()
            cache.disposables.dispose('presenceSelectionUpdate')
            cache.disposables.dispose('presenceHeartbeat')
            cache.disposables.dispose('presencePrune')
        },

        publishPresence: async (_, breakpoint) => {
            const editor = values.ttEditor
            if (!editor || editor.isDestroyed || !editor.isEditable) {
                return
            }
            await breakpoint(PRESENCE_PUBLISH_DEBOUNCE_MS)

            // Unconfirmed local steps are about to carry presence on the save path anyway.
            if (sendableSteps(editor.state)) {
                return
            }

            const head = editor.state.selection.head
            if (
                cache.lastSentPresenceHead === head &&
                Date.now() - (cache.lastSentPresenceAt ?? 0) < PRESENCE_HEARTBEAT_MS
            ) {
                return
            }

            try {
                await notebooksCollabPresenceCreate(String(getCurrentTeamId()), props.shortId, {
                    client_id: values.clientID,
                    version: getVersion(editor.state),
                    cursor: { head },
                })
                cache.lastSentPresenceHead = head
                cache.lastSentPresenceAt = Date.now()
            } catch {
                // Presence is lossy by design; the next ping self-heals.
            }
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
                    if (remote.presence) {
                        actions.handleRemotePresence({
                            clientId: remote.clientId,
                            ...remote.presence,
                            lastSeenAt: Date.now(),
                        })
                    }
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
            const controller = new AbortController()
            cache.abortController = controller

            const onMessage = (msg: EventSourceMessage): void => {
                if (msg.event === 'presence' && msg.data) {
                    const editor = values.ttEditor
                    if (!editor || editor.isDestroyed) {
                        return
                    }
                    try {
                        const payload = JSON.parse(msg.data) as {
                            client_id?: unknown
                            user_id?: unknown
                            user_name?: unknown
                            cursor?: { head?: unknown }
                        }
                        if (
                            typeof payload.client_id !== 'string' ||
                            payload.client_id === values.clientID ||
                            typeof payload.user_id !== 'number' ||
                            typeof payload.user_name !== 'string' ||
                            typeof payload.cursor?.head !== 'number'
                        ) {
                            return
                        }
                        const presence: ClientPresence = {
                            clientId: payload.client_id,
                            userId: payload.user_id,
                            userName: payload.user_name,
                            head: payload.cursor.head,
                            lastSeenAt: Date.now(),
                        }
                        actions.handleRemotePresence(presence)
                        // The extension clamps positions, so a briefly skewed version is safe.
                        editor.view.dispatch(editor.state.tr.setMeta(REMOTE_PRESENCE_META, presence))
                    } catch (e) {
                        posthog.captureException(e as Error, { action: 'notebook collab presence parse' })
                    }
                    return
                }

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
                    const remotePresence = {
                        userId: parsed.user_id,
                        userName: parsed.user_name,
                        head: parsed.cursor_head,
                    }
                    actions.handleRemotePresence({
                        clientId: parsed.client_id,
                        ...remotePresence,
                        lastSeenAt: Date.now(),
                    })
                    applyRemoteStep(editor, {
                        step: parsed.step,
                        clientId: parsed.client_id,
                        version,
                        presence: remotePresence,
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

            // onOpen fires on every successful fetch — including fetch-event-source's own
            // internal retries — so the UI flips back to "live" the moment a connection
            // opens, whether it's the initial one or a recovery after a transient error.
            const onOpen = (): void => {
                if (controller.signal.aborted) {
                    return
                }
                actions.streamOpened()
            }

            // onClose fires when the server cleanly ends the body — the backend does this
            // every STREAM_LIFETIME_SECONDS (5 min) by design. Errors and abort don't trigger
            // this hook, so it cleanly isolates the "rotation" case from the failure case.
            const onClose = (): void => {
                if (controller.signal.aborted) {
                    return
                }
                actions.streamClosed()
                actions.connectStream()
            }

            try {
                await api.notebooks.collabStream(props.shortId, {
                    onMessage,
                    onError,
                    onOpen,
                    onClose,
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
        },

        disconnectStream: () => {
            cache.abortController?.abort()
            cache.abortController = null
            cache.lastEventId = undefined
        },
    })),

    beforeUnmount(({ actions }) => {
        actions.disconnectStream()
        actions.unbindEditor()
    }),
])
