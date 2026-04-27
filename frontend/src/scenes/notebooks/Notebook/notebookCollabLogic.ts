import { EventSourceMessage } from '@microsoft/fetch-event-source'
import { getVersion, receiveTransaction } from '@tiptap/pm/collab'
import { Step } from '@tiptap/pm/transform'
import { actions, beforeUnmount, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { TTEditor } from 'lib/components/RichContentEditor/types'

import type { notebookCollabLogicType } from './notebookCollabLogicType'
import { REMOTE_PRESENCE_META, RemotePresenceUpdate } from './RemotePresenceExtension'

export type NotebookCollabProps = {
    shortId: string
}

export type RemoteStepPresence = {
    clientId: string
    userId?: number | null
    userName: string
    userColor: string
    cursorHead: number
}

export type RemoteStep = {
    step: Record<string, any>
    clientId: string
    /** Resulting version after this step is applied (== local getVersion + 1 in normal flow) */
    version: number
    presence?: RemoteStepPresence
}

type StreamStepEvent = {
    step: Record<string, any>
    client_id: string
    user_id?: number | null
    user_name?: string
    cursor_head?: number | null
}

/**
 * Idempotent step apply. The same step may arrive via SSE *and* via the 409
 * conflict body on a concurrent save; whichever lands first wins, the second
 * skips by version. Presence is always propagated so the caret stays in sync.
 */
export function applyRemoteStep(editor: TTEditor, remote: RemoteStep): void {
    const expected = getVersion(editor.state) + 1

    const presenceMeta = (): RemotePresenceUpdate | null => {
        if (!remote.presence) {
            return null
        }
        const p = remote.presence
        return {
            type: 'set',
            presence: {
                clientId: p.clientId,
                userId: p.userId ?? null,
                userName: p.userName,
                userColor: p.userColor,
                head: p.cursorHead,
            },
        }
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

    try {
        const step = Step.fromJSON(editor.state.schema, remote.step)
        let tr = receiveTransaction(editor.state, [step], [remote.clientId], {
            mapSelectionBackward: true,
        })
        const meta = presenceMeta()
        if (meta) {
            tr = tr.setMeta(REMOTE_PRESENCE_META, meta)
        }
        editor.view.dispatch(tr)
    } catch (e) {
        posthog.captureException(e as Error, { action: 'notebook collab apply remote step' })
        lemonToast.error('Failed to sync notebook changes. Please reload the page.')
    }
}

function streamEventToRemoteStep(parsed: StreamStepEvent, version: number): RemoteStep {
    return {
        step: parsed.step,
        clientId: parsed.client_id,
        version,
        presence:
            parsed.user_name && typeof parsed.cursor_head === 'number'
                ? {
                      clientId: parsed.client_id,
                      userId: parsed.user_id ?? null,
                      userName: parsed.user_name,
                      // Stable presence color from PostHog's data palette; anonymous users get slot 0.
                      userColor: getSeriesColor(typeof parsed.user_id === 'number' ? parsed.user_id : 0),
                      cursorHead: parsed.cursor_head,
                  }
                : undefined,
    }
}

export const notebookCollabLogic = kea<notebookCollabLogicType>([
    props({} as NotebookCollabProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookCollabLogic', key]),
    key(({ shortId }) => shortId),

    actions({
        bindEditor: (clientID: string, editor: TTEditor) => ({ clientID, editor }),
        unbindEditor: (clientID: string) => ({ clientID }),
        ackLocalSteps: (steps: Record<string, any>[], clientID: string) => ({ steps, clientID }),
        applyRemoteSteps: (steps: RemoteStep[]) => ({ steps }),
        connectStream: true,
        disconnectStream: true,
    }),

    reducers({
        // Multiple instances of the same notebook can be mounted in one browser tab
        // (e.g. within multiple PostHog tabs); each gets its own PM-collab clientID.
        editors: [
            {} as Record<string, TTEditor>,
            {
                bindEditor: (state, { clientID, editor }) => ({ ...state, [clientID]: editor }),
                unbindEditor: (state, { clientID }) => {
                    const next = { ...state }
                    delete next[clientID]
                    return next
                },
            },
        ],
    }),

    listeners(({ actions, values, props, cache }) => ({
        bindEditor: () => {
            // Open the stream on the first bind; subsequent binds use the same connection.
            if (Object.keys(values.editors).length === 1) {
                actions.connectStream()
            }
        },

        unbindEditor: () => {
            if (Object.keys(values.editors).length === 0) {
                actions.disconnectStream()
            }
        },

        ackLocalSteps: ({ steps, clientID }) => {
            if (!steps.length) {
                return
            }
            const editor = values.editors[clientID]
            if (!editor) {
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
            // Fan out to every bound editor; each skips its own echo via clientID.
            for (const [clientID, editor] of Object.entries(values.editors)) {
                for (const remote of steps) {
                    if (remote.clientId === clientID) {
                        continue
                    }
                    applyRemoteStep(editor, remote)
                }
            }
        },

        connectStream: async () => {
            cache.abortController?.abort()
            const controller = new AbortController()
            cache.abortController = controller

            const onMessage = (msg: EventSourceMessage): void => {
                if (msg.event !== 'step' || !msg.data) {
                    return
                }
                // SSE id is the Redis stream id `N-0` and N is the prosemirror version.
                // We use it for both reconnection (Last-Event-ID) and idempotency.
                const version = parseInt(msg.id.split('-', 1)[0], 10)
                if (!Number.isFinite(version)) {
                    return
                }
                let parsed: StreamStepEvent
                try {
                    parsed = JSON.parse(msg.data)
                } catch (e) {
                    posthog.captureException(e as Error, { action: 'notebook collab stream parse' })
                    return
                }
                actions.applyRemoteSteps([streamEventToRemoteStep(parsed, version)])
            }

            const onError = (error: any): void => {
                if (controller.signal.aborted) {
                    return
                }
                posthog.captureException(error instanceof Error ? error : new Error(String(error)), {
                    action: 'notebook collab stream',
                })
            }

            // fetchEventSource handles reconnection via Last-Event-ID; this awaits for the connection's lifetime.
            try {
                await api.notebooks.collabStream(props.shortId, {
                    onMessage,
                    onError,
                    signal: controller.signal,
                })
            } catch (e) {
                if (controller.signal.aborted) {
                    return
                }
                posthog.captureException(e as Error, { action: 'notebook collab stream open' })
            }
        },

        disconnectStream: () => {
            cache.abortController?.abort()
            cache.abortController = null
        },
    })),

    beforeUnmount(({ actions }) => {
        actions.disconnectStream()
    }),
])
