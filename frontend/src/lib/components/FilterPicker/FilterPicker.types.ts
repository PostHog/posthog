import { ReactNode } from 'react'

export interface FilterPickerPath {
    nodeIds: string[]
}

export interface FilterPickerSection {
    id: string
    label: ReactNode
    icon?: ReactNode
}

export interface FilterPickerChildrenContext {
    query: string
    path: FilterPickerPath
}

export interface FilterPickerChildrenResult {
    nodes: FilterPickerNode[]
    isLoading?: boolean
    hasMore?: boolean
    loadMore?: () => void
    isLoadingMore?: boolean
    emptyMessage?: ReactNode
}

export interface FilterPickerSelectContext {
    close: () => void
    resetToRoot: () => void
    path: FilterPickerPath
}

export interface FilterPickerPanelContext extends FilterPickerSelectContext {
    query: string
    setQuery: (query: string) => void
}

export interface FilterPickerNode {
    id: string
    label: ReactNode
    tokenLabel?: ReactNode
    /** Word-form label shown in the in-picker breadcrumb (e.g. "contains"); falls back to tokenLabel/label. */
    breadcrumbLabel?: ReactNode
    searchableText?: string[]
    description?: ReactNode
    hint?: ReactNode
    disabledReason?: string
    section?: FilterPickerSection
    kind: 'branch' | 'action' | 'panel'
    searchPlaceholder?: string
    /**
     * Returns the child nodes to render for this node. MUST be pure and cheap: it is also called during
     * path resolution on every render, so it may not fetch, dispatch, or mutate. Trigger any data loading
     * from `loadContent` instead. The unfiltered result must be a superset of the query-filtered one so
     * path resolution (which calls this with an empty query) can always find a committed child.
     */
    getChildren?: (context: FilterPickerChildrenContext) => FilterPickerChildrenResult
    /**
     * Imperative side-effect hook for the active node, called from an effect keyed on the node id + query.
     * Use this to kick off async loads whose results then flow back through `getChildren`.
     */
    loadContent?: (context: FilterPickerChildrenContext) => void
    onSelect?: (context: FilterPickerSelectContext) => void
    renderPanel?: (context: FilterPickerPanelContext) => ReactNode
}

export interface FilterPickerTokenPart {
    key?: string
    kind: 'property' | 'operator' | 'value' | 'text'
    label: ReactNode
    ariaLabel?: string
}

export interface FilterPickerToken {
    id: string
    parts: FilterPickerTokenPart[]
    title?: string
    editPath?: FilterPickerPath
    removable?: boolean
    editable?: boolean
    onRemove?: () => void
}
