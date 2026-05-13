import { NodeViewWrapper } from '@tiptap/react'
import { Component, ReactNode } from 'react'

import { IconWarning } from '@posthog/icons'

import { NotebookNodeType } from '../types'

/**
 * Node types that are safe to render inside a publicly shared notebook today.
 *
 * Anything not in this set falls back to {@link UnsupportedNodePlaceholder} so that
 * shared notebook viewers never crash on a node we haven't audited for anonymous use yet.
 *
 * To add a new supported node:
 *   1. Confirm the node only fetches data via endpoints that accept `SharingAccessTokenAuthentication`.
 *   2. Confirm it has no editor-only side effects when `isEditable=false`.
 *   3. Add the entry below.
 *
 * Built-in ProseMirror / StarterKit / Tiptap node names (paragraph, heading, bulletList, etc.) are
 * registered separately in `Editor.tsx` and aren't gated through this list \u2014 only PostHog widget
 * nodes (`ph-*`) flow through `createPostHogWidgetNode` where this check runs.
 */
export const SHARED_NOTEBOOK_SUPPORTED_NODE_TYPES: ReadonlySet<string> = new Set([
    NotebookNodeType.Image,
    NotebookNodeType.Latex,
    NotebookNodeType.Embed,
    // `ph-query` itself is allow-listed at the node-type level, but the component does its own
    // shared-mode check internally: only `SavedInsightNode` queries with a backend-pre-computed
    // result render. Inline / ad-hoc queries (DataTableNode, HogQLQuery, etc.) fall back to
    // `UnsupportedNodePlaceholder` from inside `NotebookNodeQuery` because they would otherwise
    // POST to `/api/projects/.../query/`, which sharing tokens cannot reach.
    NotebookNodeType.Query,
])

export function isNodeSupportedInSharedNotebook(nodeType: string): boolean {
    return SHARED_NOTEBOOK_SUPPORTED_NODE_TYPES.has(nodeType)
}

export function UnsupportedNodePlaceholder(): JSX.Element {
    return (
        <NodeViewWrapper
            as="div"
            className="NotebookNode--unsupported my-2 rounded border border-dashed border-warning bg-warning-highlight p-3"
            data-attr="notebook-unsupported-node"
            contentEditable={false}
        >
            <div className="flex items-start gap-2">
                <IconWarning className="text-warning mt-0.5 shrink-0 text-lg" />
                <div className="flex flex-col">
                    <span className="font-medium">Node cannot be rendered</span>
                    <span className="text-secondary text-sm">
                        This node type is not supported in shared notebooks. We are working on supporting it soon!
                    </span>
                </div>
            </div>
        </NodeViewWrapper>
    )
}

/**
 * Tiny error boundary used only by the shared-notebook render path. Catches anything that throws
 * while rendering an allow-listed node and falls back to the same placeholder so the surrounding
 * notebook keeps rendering. The full `~/layout/ErrorBoundary` is intentionally not used here
 * because it shows engineer-oriented support UI which we don't want anonymous viewers to see.
 */
interface SharedNodeErrorBoundaryProps {
    children: ReactNode
}

export class SharedNodeErrorBoundary extends Component<SharedNodeErrorBoundaryProps, { hasError: boolean }> {
    override state = { hasError: false }

    static getDerivedStateFromError(): { hasError: boolean } {
        return { hasError: true }
    }

    override componentDidCatch(): void {
        // Swallow errors: a single broken node should not surface a stack trace to public viewers.
        // The exception is still reported via the global error handler attached at app boot.
    }

    override render(): ReactNode {
        if (this.state.hasError) {
            return <UnsupportedNodePlaceholder />
        }
        return this.props.children
    }
}
