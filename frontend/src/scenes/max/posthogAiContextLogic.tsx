import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import type { ReactNode } from 'react'

import { IconDashboard, IconGraph, IconNotebook } from '@posthog/icons'

import { IconAction, IconEvent } from 'lib/lemon-ui/icons'
import { sceneLogic } from 'scenes/sceneLogic'

import { AttachedContext, MaxContextInput, MaxContextType } from './maxTypes'
import type { posthogAiContextLogicType } from './posthogAiContextLogicType'

export interface PosthogAiContextLogicProps {
    conversationId: string
}

/** Stable dedupe + chip key for an attachment: `${type}:${id ?? value}`. */
export function attachedContextKey(item: AttachedContext): string {
    return `${item.type}:${item.id ?? item.value ?? ''}`
}

/**
 * Projects a rich scene `MaxContextInput` down to the flat `AttachedContext` shape the sandbox
 * runtime sends. Strips nested entity data — the agent fetches details via its read tools.
 * Returns null for inputs that have no flat representation.
 */
export function projectToAttachedContext(item: MaxContextInput): AttachedContext | null {
    switch (item.type) {
        case MaxContextType.DASHBOARD:
            return { type: 'dashboard', id: item.data.id, name: item.data.name ?? undefined }
        case MaxContextType.INSIGHT:
            return { type: 'insight', id: item.data.short_id, name: item.data.name ?? undefined }
        case MaxContextType.EVENT:
            return { type: 'event', id: item.data.id, name: item.data.name ?? undefined }
        case MaxContextType.ACTION:
            return { type: 'action', id: item.data.id, name: item.data.name ?? undefined }
        case MaxContextType.ERROR_TRACKING_ISSUE:
            return { type: 'error_tracking_issue', id: item.data.id, name: item.data.name ?? undefined }
        case MaxContextType.EVALUATION:
            return { type: 'evaluation', id: item.data.id, name: item.data.name ?? undefined }
        case MaxContextType.NOTEBOOK:
            return { type: 'notebook', id: item.data.short_id, name: item.data.title ?? undefined }
        default:
            return null
    }
}

function iconForType(type: AttachedContext['type']): ReactNode {
    switch (type) {
        case 'dashboard':
            return <IconDashboard />
        case 'insight':
            return <IconGraph />
        case 'event':
            return <IconEvent />
        case 'action':
            return <IconAction />
        case 'notebook':
            return <IconNotebook />
        default:
            return <IconGraph />
    }
}

function labelForItem(item: AttachedContext): string {
    if (item.type === 'text') {
        return item.value ?? 'Text'
    }
    if (item.name) {
        return item.name
    }
    return `${item.type} ${item.id ?? ''}`.trim()
}

/**
 * Sandbox-runtime context store. Holds one flat `attachments` reducer plus a scene-pull
 * listener that reads the existing scenes' `maxContext` selectors and projects their rich
 * items down to `AttachedContext` at consumption time — zero scene-side edits.
 *
 * Coexistence sibling to `maxContextLogic.ts`; used only when `agent_runtime === 'sandbox'`.
 *
 * Keyed by conversation id so each conversation keeps its own attachment set.
 */
export const posthogAiContextLogic = kea<posthogAiContextLogicType>([
    props({} as PosthogAiContextLogicProps),
    key((props) => props.conversationId),
    path((key) => ['scenes', 'max', 'posthogAiContextLogic', key]),
    connect(() => ({
        values: [sceneLogic, ['activeSceneLogic']],
    })),
    actions({
        /** Dedup-add. Called by scene sync AND by the TaxonomicFilter affordance. */
        attach: (item: AttachedContext) => ({ item }),
        /** Remove by `${type}:${id ?? value}` key. */
        detach: (key: string) => ({ key }),
        /** Convenience reset, e.g. on a new conversation. */
        clearAttachments: true,
        /** Router/scene listener — projects every current-scene item and attaches it. */
        syncSceneAttachments: true,
    }),
    reducers({
        attachments: [
            [] as AttachedContext[],
            {
                attach: (state, { item }) => {
                    const key = attachedContextKey(item)
                    // Text items are never deduped — repeated text is intentional.
                    if (item.type !== 'text' && state.some((existing) => attachedContextKey(existing) === key)) {
                        return state
                    }
                    return [...state, item]
                },
                detach: (state, { key }) => state.filter((item) => attachedContextKey(item) !== key),
                clearAttachments: () => [],
            },
        ],
    }),
    selectors({
        chipsForDisplay: [
            (s) => [s.attachments],
            // No onRemove closures here — removal dispatches `detach(key)` on the consumer's
            // bound instance, so chips stay instance-agnostic data.
            (attachments): { key: string; label: string; icon: ReactNode }[] =>
                attachments.map((item) => ({
                    key: attachedContextKey(item),
                    label: labelForItem(item),
                    icon: iconForType(item.type),
                })),
        ],
    }),
    listeners(({ values, actions }) => ({
        syncSceneAttachments: () => {
            const activeSceneLogic = values.activeSceneLogic
            if (!activeSceneLogic || !('maxContext' in activeSceneLogic.selectors)) {
                return
            }
            let sceneItems: MaxContextInput[] = []
            try {
                // BuiltLogic exposes selector results on `.values`; props are already bound.
                sceneItems = (activeSceneLogic.values as { maxContext?: MaxContextInput[] }).maxContext ?? []
            } catch (error) {
                // The scene's maxContext selector threw (e.g. dereferencing still-loading state).
                // Capture so the dropped attach is observable instead of silent; nothing to attach.
                posthog.captureException(error)
                return
            }
            for (const item of sceneItems) {
                const projected = projectToAttachedContext(item)
                if (projected) {
                    actions.attach(projected)
                }
            }
        },
    })),
])
