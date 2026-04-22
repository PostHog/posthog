import { Extension } from '@tiptap/core'
import { EditorState, Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

export type RemotePresence = {
    clientId: string
    userId?: number | null
    userName: string
    userColor: string
    head: number
    lastSeenAt: number
}

type PluginState = {
    /** keyed by clientId */
    presences: Map<string, RemotePresence>
}

export const REMOTE_PRESENCE_META = 'remote-presence-update'
const META_KEY = REMOTE_PRESENCE_META
const PRESENCE_TTL_MS = 30_000
const META_PRUNE = 'remote-presence-prune'

export type RemotePresenceUpdate = UpdatePayload

export const remotePresencePluginKey = new PluginKey<PluginState>('remote-presence')

type UpdatePayload =
    | { type: 'set'; presence: Omit<RemotePresence, 'lastSeenAt'> & { lastSeenAt?: number } }
    | { type: 'remove'; clientId: string }
    | { type: 'clear' }

function buildDecorations(state: EditorState, presences: Map<string, RemotePresence>): DecorationSet {
    if (presences.size === 0) {
        return DecorationSet.empty
    }
    const docSize = state.doc.content.size
    const decorations: Decoration[] = []

    for (const presence of presences.values()) {
        const head = clamp(presence.head, 0, docSize)

        // Caret as a side-positioned widget. side:-1 keeps it in front of any
        // text inserted at the same position by the local user, so the local
        // caret still wins visually. Range-selection highlights will land with
        // the separate :presence-stream (clicks/drags without edits).
        decorations.push(
            Decoration.widget(head, () => buildCaretDom(presence), {
                key: `presence-${presence.clientId}`,
                side: -1,
            })
        )
    }

    return DecorationSet.create(state.doc, decorations)
}

function buildCaretDom(presence: RemotePresence): HTMLElement {
    const root = document.createElement('span')
    root.className = 'NotebookRemotePresence'
    root.style.setProperty('--remote-presence-color', presence.userColor)
    root.dataset.clientId = presence.clientId

    const flag = document.createElement('span')
    flag.className = 'NotebookRemotePresence__flag'
    flag.textContent = presence.userName
    root.appendChild(flag)

    return root
}

function clamp(n: number, min: number, max: number): number {
    if (n < min) {
        return min
    }
    if (n > max) {
        return max
    }
    return n
}

function pruneStale(presences: Map<string, RemotePresence>, now: number): Map<string, RemotePresence> | null {
    let next: Map<string, RemotePresence> | null = null
    for (const [id, p] of presences) {
        if (now - p.lastSeenAt > PRESENCE_TTL_MS) {
            if (!next) {
                next = new Map(presences)
            }
            next.delete(id)
        }
    }
    return next
}

export const RemotePresenceExtension = Extension.create({
    name: 'remotePresence',

    addProseMirrorPlugins() {
        const plugin = new Plugin<PluginState>({
            key: remotePresencePluginKey,
            state: {
                init: () => ({ presences: new Map() }),
                apply: (transaction, prev): PluginState => {
                    let presences = prev.presences

                    // 1. Project stored positions (pre-transaction coords) forward through any doc changes.
                    if (transaction.docChanged && presences.size > 0) {
                        const mapped = new Map<string, RemotePresence>()
                        for (const [id, p] of presences) {
                            mapped.set(id, { ...p, head: transaction.mapping.map(p.head) })
                        }
                        presences = mapped
                    }

                    // 2. Apply meta after mapping: an upsert piggybacked on a remote step already
                    //    carries post-transaction coords, so mapping it again would double-shift.
                    const meta = transaction.getMeta(META_KEY) as UpdatePayload | undefined
                    if (meta) {
                        switch (meta.type) {
                            case 'set': {
                                presences = new Map(presences)
                                presences.set(meta.presence.clientId, {
                                    ...meta.presence,
                                    lastSeenAt: meta.presence.lastSeenAt ?? Date.now(),
                                })
                                break
                            }
                            case 'remove': {
                                if (presences.has(meta.clientId)) {
                                    presences = new Map(presences)
                                    presences.delete(meta.clientId)
                                }
                                break
                            }
                            case 'clear': {
                                presences = new Map()
                                break
                            }
                        }
                    } else if (transaction.getMeta(META_PRUNE)) {
                        const pruned = pruneStale(presences, Date.now())
                        if (pruned) {
                            presences = pruned
                        }
                    }

                    return presences === prev.presences ? prev : { presences }
                },
            },
            props: {
                decorations(state) {
                    const pluginState = remotePresencePluginKey.getState(state)
                    if (!pluginState) {
                        return null
                    }
                    return buildDecorations(state, pluginState.presences)
                },
            },
            view: (view) => {
                // Periodic prune so abandoned remote carets fade out even if
                // we never receive another transaction for the doc.
                const interval = window.setInterval(() => {
                    const pluginState = remotePresencePluginKey.getState(view.state)
                    if (!pluginState || pluginState.presences.size === 0) {
                        return
                    }
                    const stale = pruneStale(pluginState.presences, Date.now())
                    if (stale) {
                        view.dispatch(view.state.tr.setMeta(META_PRUNE, true))
                    }
                }, 5_000)
                return {
                    destroy() {
                        window.clearInterval(interval)
                    },
                }
            },
        })

        return [plugin]
    },
})
