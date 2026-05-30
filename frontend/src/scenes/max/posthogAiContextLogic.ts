import { actions, getContext, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { ReactNode, createElement } from 'react'

import { IconDashboard, IconGraph, IconLetter, IconNotebook } from '@posthog/icons'

import { IconAction, IconEvent } from 'lib/lemon-ui/icons'
import { sceneLogic } from 'scenes/sceneLogic'

import { MaxContextInput, MaxContextType } from './maxTypes'
import { AttachedContext } from './maxTypes'
import type { posthogAiContextLogicType } from './posthogAiContextLogicType'

/**
 * Sandbox-runtime context logic (sibling to maxContextLogic.ts, which stays untouched for
 * the LangGraph runtime). Holds one flat `attachments` reducer. Both user-attached items
 * (TaxonomicFilter / @-mention) and scene-projected items flow through the same `attach`
 * action — there is no manual-vs-scene split and no separate persistence policy.
 *
 * Mounted by maxThreadLogic only when conversation.agent_runtime === 'sandbox'.
 * See docs/internal/posthog-ai-migration/01_CONTEXT.md §3.
 */

export interface PostHogAiContextChip {
    key: string
    label: string
    icon: ReactNode
    onRemove: () => void
}

export interface PostHogAiContextLogicProps {
    /** Threads its key so per-conversation context stays isolated. */
    conversationKey: string
}

/** Stable dedup/removal key. `text` items key on their value; entity refs key on id. */
export function keyForAttachment(item: AttachedContext): string {
    return `${item.type}:${item.id ?? item.value ?? ''}`
}

// JSX is not allowed in a .ts file; build icon nodes with createElement.
const ICON_FOR_TYPE: Record<AttachedContext['type'], ReactNode> = {
    dashboard: createElement(IconDashboard),
    insight: createElement(IconGraph),
    event: createElement(IconEvent),
    action: createElement(IconAction),
    error_tracking_issue: createElement(IconGraph),
    evaluation: createElement(IconGraph),
    notebook: createElement(IconNotebook),
    text: createElement(IconLetter),
}

function defaultLabel(item: AttachedContext): string {
    if (item.type === 'text') {
        return item.value ?? 'Text'
    }
    if (item.name) {
        return item.name
    }
    return item.id != null ? `${item.type} ${item.id}` : item.type
}

/**
 * Project a rich scene `MaxContextInput` down to a flat `AttachedContext`. Reads the
 * existing scene shapes READ-ONLY — zero edits to maxContextLogic.ts or any scene logic.
 * Returns null for shapes that don't map to an attachment.
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

/**
 * Read the active scene's `maxContext` selector without mounting or editing it. Mirrors
 * maxContextLogic.rawSceneContext verbatim — same scene-props plumbing, just read-only.
 */
function readSceneContext(): MaxContextInput[] {
    if (!sceneLogic.isMounted()) {
        return []
    }
    const state = getContext().store.getState()
    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, {})
    if (activeSceneLogic && 'maxContext' in activeSceneLogic.selectors) {
        try {
            const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, {})
            return activeSceneLogic.selectors.maxContext(
                state,
                activeLoadedScene?.paramsToProps?.(activeLoadedScene?.sceneParams) || {}
            )
        } catch {
            // A failing scene selector must never break context attachment.
        }
    }
    return []
}

export const posthogAiContextLogic = kea<posthogAiContextLogicType>([
    path((key) => ['scenes', 'max', 'posthogAiContextLogic', key]),
    props({} as PostHogAiContextLogicProps),
    key((props) => props.conversationKey),

    actions({
        /** Dedup-add. Called by the scene sync AND by TaxonomicFilter / @-mention. */
        attach: (item: AttachedContext) => ({ item }),
        /** Remove by `keyForAttachment` key. */
        detach: (key: string) => ({ key }),
        /** Convenience reset (e.g. on new conversation). */
        clearAttachments: true,
        /** Project every active-scene context item and attach it (no-op if already present). */
        syncSceneAttachments: true,
    }),

    reducers({
        attachments: [
            [] as AttachedContext[],
            {
                attach: (state, { item }) => {
                    const key = keyForAttachment(item)
                    if (state.some((existing) => keyForAttachment(existing) === key)) {
                        return state
                    }
                    return [...state, item]
                },
                detach: (state, { key }) => state.filter((item) => keyForAttachment(item) !== key),
                clearAttachments: () => [],
            },
        ],
    }),

    selectors(({ props }) => ({
        chipsForDisplay: [
            (s) => [s.attachments],
            (attachments: AttachedContext[]): PostHogAiContextChip[] =>
                attachments.map((item) => {
                    const key = keyForAttachment(item)
                    return {
                        key,
                        label: defaultLabel(item),
                        icon: ICON_FOR_TYPE[item.type],
                        // Bind removal to this keyed instance so per-conversation context stays isolated.
                        onRemove: () => posthogAiContextLogic(props).actions.detach(key),
                    }
                }),
        ],
    })),

    listeners(({ actions }) => ({
        syncSceneAttachments: () => {
            for (const sceneItem of readSceneContext()) {
                const projected = projectToAttachedContext(sceneItem)
                if (projected) {
                    actions.attach(projected)
                }
            }
        },
    })),
])
