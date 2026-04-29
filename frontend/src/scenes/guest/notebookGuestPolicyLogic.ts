/**
 * Notebook guest policy — single source of truth for "what can a guest do on a
 * notebook scene" (which menu actions render, whether optimistic edits persist, which
 * embedded TipTap node types are allowed to render).
 *
 * Rooted in the AC layer's `user_access_level` for the notebook so non-guests see no
 * behavior change — every selector returns the same answer for a non-guest as it always
 * has. Guest viewers (no editor-level AC) collapse all admin affordances onto one anchor
 * (`canEdit`), and the embedded-node renderer consults `canRenderEmbeddedNode(nodeType)`.
 *
 * Two surfaces are exported from this file:
 *  - `notebookGuestPolicy(user, notebook)` — pure function. Used by `notebookLogic` and
 *    other places that would create a kea-logic dependency cycle if they consumed the
 *    logic below. Keep these call sites narrow.
 *  - `notebookGuestPolicyLogic({ shortId })` — reactive kea logic. The default consumer
 *    surface for components (notebook menu, node wrapper, etc.).
 *
 * Both surfaces compute the exact same answer; the logic is a thin kea wrapper around
 * the function so the centralization holds.
 */

import { connect, kea, key, path, props, selectors } from 'kea'

import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { userLogic } from 'scenes/userLogic'

import { AccessControlLevel, AccessControlResourceType, NotebookType, UserType } from '~/types'

import { notebookLogic } from '../notebooks/Notebook/notebookLogic'
import type { notebookGuestPolicyLogicType } from './notebookGuestPolicyLogicType'

/** Notebook node `type` strings a guest is allowed to render in the embedded-node renderer.
 *
 * Mirrors `posthog/rbac/notebook_cascade.py::NOTEBOOK_NODE_CASCADE` keys plus the inert
 * presentation-only nodes (latex, image, embed, mention, replay-timestamp). Anything not
 * in this set renders a guest placeholder — most importantly the executable / admin
 * nodes (`ph-python`, `ph-hogql-sql`, `ph-duck-sql`, `ph-task-create`, `ph-llm-trace`,
 * `ph-issues`, etc.) which would otherwise fire requests the guest can't satisfy.
 *
 * Adding a new node type to the BE cascade table? Mirror it here. The two lists answer
 * different questions but must stay in sync.
 */
export const NOTEBOOK_NODE_GUEST_RENDERABLE_TYPES: ReadonlySet<string> = new Set([
    // Cascadeable (BE writes AC rows on grant): see notebook_cascade.py
    'ph-query',
    'ph-recording',
    'ph-recording-playlist',
    'ph-cohort',
    'ph-feature-flag',
    'ph-feature-flag-code-example',
    'ph-experiment',
    'ph-early-access-feature',
    'ph-survey',
    'ph-backlink',
    // Presentation-only / inert: safe to render, no resource request fired
    'ph-latex',
    'ph-image',
    'ph-embed',
    'ph-replay-timestamp',
    'mention',
    // Person / group nodes are server-rendered through the team-scoped read which the
    // notebook AC row already authorizes. Allow render; the BE deflects if AC layer denies.
    'ph-person',
    'ph-person-properties',
    'ph-person-feed',
    'ph-group',
    'ph-group-properties',
    'ph-related-groups',
    // Tiptap structural nodes — block-level wrappers that contain other nodes. Always allowed.
    'doc',
    'paragraph',
    'heading',
    'bulletList',
    'orderedList',
    'listItem',
    'taskList',
    'taskItem',
    'blockquote',
    'codeBlock',
    'horizontalRule',
    'hardBreak',
    'text',
])

export interface NotebookGuestPolicy {
    isGuest: boolean
    isGuestViewer: boolean
    canEdit: boolean
    canDelete: boolean
    canDuplicate: boolean
    canExportJSON: boolean
    canViewHistory: boolean
    canShare: boolean
    canPerformActions: boolean
    blockOptimisticPersist: boolean
    canRenderEmbeddedNode: (nodeType: string) => boolean
}

/** Pure-function form of the policy. Avoids logic-to-logic cycles when called from
 *  inside another kea logic (e.g. `notebookLogic.loadNotebookSuccess`). */
export function notebookGuestPolicy(user: UserType | null, notebook: NotebookType | null): NotebookGuestPolicy {
    const isGuest = !!user?.is_guest_in_current_project
    const acLevel = notebook?.user_access_level
    const canEdit =
        !!acLevel && accessLevelSatisfied(AccessControlResourceType.Notebook, acLevel, AccessControlLevel.Editor)

    if (!isGuest) {
        return {
            isGuest: false,
            isGuestViewer: false,
            canEdit,
            canDelete: true,
            canDuplicate: true,
            canExportJSON: true,
            canViewHistory: true,
            canShare: true,
            canPerformActions: true,
            blockOptimisticPersist: false,
            canRenderEmbeddedNode: () => true,
        }
    }

    const canDelete = canEdit
    const canDuplicate = canEdit
    const canExportJSON = canEdit
    const canViewHistory = canEdit
    const canShare = canEdit
    return {
        isGuest: true,
        isGuestViewer: !canEdit,
        canEdit,
        canDelete,
        canDuplicate,
        canExportJSON,
        canViewHistory,
        canShare,
        canPerformActions: canEdit || canDelete || canDuplicate || canExportJSON || canViewHistory || canShare,
        blockOptimisticPersist: !canEdit,
        canRenderEmbeddedNode: (nodeType) => NOTEBOOK_NODE_GUEST_RENDERABLE_TYPES.has(nodeType),
    }
}

export interface NotebookGuestPolicyLogicProps {
    shortId: string
}

export const notebookGuestPolicyLogic = kea<notebookGuestPolicyLogicType>([
    props({} as NotebookGuestPolicyLogicProps),
    key((p) => p.shortId),
    path((key) => ['scenes', 'guest', 'notebookGuestPolicyLogic', key]),

    connect((p: NotebookGuestPolicyLogicProps) => ({
        values: [userLogic, ['user'], notebookLogic({ shortId: p.shortId }), ['notebook']],
    })),

    selectors({
        // Single derived selector — every consumer-facing flag projects from this so the
        // pure function and the reactive logic can never drift.
        policy: [
            (s) => [s.user, s.notebook],
            (user, notebook): NotebookGuestPolicy => notebookGuestPolicy(user, notebook),
        ],

        isGuest: [(s) => [s.policy], (policy): boolean => policy.isGuest],
        isGuestViewer: [(s) => [s.policy], (policy): boolean => policy.isGuestViewer],
        canEdit: [(s) => [s.policy], (policy): boolean => policy.canEdit],
        canDelete: [(s) => [s.policy], (policy): boolean => policy.canDelete],
        canDuplicate: [(s) => [s.policy], (policy): boolean => policy.canDuplicate],
        canExportJSON: [(s) => [s.policy], (policy): boolean => policy.canExportJSON],
        canViewHistory: [(s) => [s.policy], (policy): boolean => policy.canViewHistory],
        canShare: [(s) => [s.policy], (policy): boolean => policy.canShare],
        canPerformActions: [(s) => [s.policy], (policy): boolean => policy.canPerformActions],
        blockOptimisticPersist: [(s) => [s.policy], (policy): boolean => policy.blockOptimisticPersist],
        canRenderEmbeddedNode: [
            (s) => [s.policy],
            (policy): ((nodeType: string) => boolean) => policy.canRenderEmbeddedNode,
        ],
    }),
])
