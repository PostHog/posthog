import { Extension } from '@tiptap/core'
import { EditorState, Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

import { getSeriesColor } from 'lib/colors'

import type { RemotePresence } from './notebookCollabLogic'

// Remote presence, used both as:
// - the meta payload dispatched to the plugin `transaction.setMeta(REMOTE_PRESENCE_META, ...)`
// - the per-client value stored in plugin state
// `lastSeenAt` is stamped by the logic at dispatch time and used here only for TTL pruning.
export type ClientPresence = RemotePresence & {
    clientId: string
    lastSeenAt: number
}

type PluginState = {
    // keyed by clientId
    clients: Map<string, ClientPresence>
}

export const REMOTE_PRESENCE_META = 'remote-presence-update'
const META_PRUNE = 'remote-presence-prune'
const PRESENCE_TTL_MS = 30_000

export const remotePresencePluginKey = new PluginKey<PluginState>('remote-presence')

function buildDecorations(state: EditorState, clients: Map<string, ClientPresence>): DecorationSet {
    if (clients.size === 0) {
        return DecorationSet.empty
    }
    const docSize = state.doc.content.size
    const decorations: Decoration[] = []

    for (const presence of clients.values()) {
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

function buildCaretDom(presence: ClientPresence): HTMLElement {
    const root = document.createElement('span')
    root.className = 'NotebookRemotePresence'
    root.style.setProperty('--remote-presence-color', getSeriesColor(presence.userId))
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

function pruneStale(clients: Map<string, ClientPresence>, now: number): Map<string, ClientPresence> | null {
    let next: Map<string, ClientPresence> | null = null
    for (const [id, p] of clients) {
        if (now - p.lastSeenAt > PRESENCE_TTL_MS) {
            if (!next) {
                next = new Map(clients)
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
                init: () => ({ clients: new Map() }),
                apply: (transaction, prev): PluginState => {
                    let clients = prev.clients

                    // 1. Project stored positions (pre-transaction coords) forward through any doc changes.
                    if (transaction.docChanged && clients.size > 0) {
                        const mapped = new Map<string, ClientPresence>()
                        for (const [id, p] of clients) {
                            mapped.set(id, { ...p, head: transaction.mapping.map(p.head) })
                        }
                        clients = mapped
                    }

                    // 2. Apply meta after mapping: an upsert piggybacked on a remote step already
                    //    carries post-transaction coords, so mapping it again would double-shift.
                    const meta = transaction.getMeta(REMOTE_PRESENCE_META) as ClientPresence | undefined
                    if (meta) {
                        clients = new Map(clients)
                        clients.set(meta.clientId, meta)
                    } else if (transaction.getMeta(META_PRUNE)) {
                        const pruned = pruneStale(clients, Date.now())
                        if (pruned) {
                            clients = pruned
                        }
                    }

                    return clients === prev.clients ? prev : { clients }
                },
            },
            props: {
                decorations(state) {
                    const pluginState = remotePresencePluginKey.getState(state)
                    if (!pluginState) {
                        return null
                    }
                    return buildDecorations(state, pluginState.clients)
                },
            },
            view: (view) => {
                // Periodic prune so abandoned remote carets fade out even if
                // we never receive another transaction for the doc.
                const interval = window.setInterval(() => {
                    const pluginState = remotePresencePluginKey.getState(view.state)
                    if (!pluginState || pluginState.clients.size === 0) {
                        return
                    }
                    const stale = pruneStale(pluginState.clients, Date.now())
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
