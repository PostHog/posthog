import { EventSourceMessage } from '@microsoft/fetch-event-source'
import { getVersion, receiveTransaction } from '@tiptap/pm/collab'
import { Step } from '@tiptap/pm/transform'
import { actions, beforeUnmount, kea, key, listeners, path, props, reducers } from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'
import { TTEditor } from 'lib/components/RichContentEditor/types'
import { uuid } from 'lib/utils'

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

export type StreamStepEvent = {
    step: Record<string, any>
    client_id: string
    user_id?: number | null
    user_name?: string
    cursor_head?: number | null
}

/** Stable presence color from PostHog's data palette; anonymous users get slot 0 */
function userColor(userId: number | null | undefined): string {
    return getSeriesColor(typeof userId === 'number' ? userId : 0)
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

export function streamEventToRemoteStep(parsed: StreamStepEvent, version: number): RemoteStep {
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
                      userColor: userColor(parsed.user_id),
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
        bindEditor: (editor: TTEditor) => ({ editor }),
        unbindEditor: true,
        /** Ack our own saved steps so PM-collab advances its version (matching clientID = no-op apply). */
        ackLocalSteps: (steps: Record<string, any>[], clientID: string) => ({ steps, clientID }),
        /** Apply steps received from SSE or a 409 body. Idempotent by version. */
        applyRemoteSteps: (steps: RemoteStep[]) => ({ steps }),
        connectStream: true,
        disconnectStream: true,
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
            if (!editor || !steps.length) {
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
            if (!editor) {
                return
            }
            for (const remote of steps) {
                if (remote.clientId === values.clientID) {
                    continue
                }
                applyRemoteStep(editor, remote)
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
                if (parsed.client_id === values.clientID) {
                    return
                }
                const editor = values.ttEditor
                if (!editor) {
                    return
                }
                applyRemoteStep(editor, streamEventToRemoteStep(parsed, version))
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
        actions.unbindEditor()
    }),
])
