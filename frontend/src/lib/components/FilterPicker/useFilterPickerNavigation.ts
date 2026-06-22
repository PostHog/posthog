import { MutableRefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { FilterPickerNode, FilterPickerPath } from './FilterPicker.types'

const ROOT_ID = '__root__'

function pathKey(path?: FilterPickerPath): string {
    return path?.nodeIds.join('/') ?? ''
}

function createRootNode(rootNodesRef: MutableRefObject<FilterPickerNode[]>, placeholder?: string): FilterPickerNode {
    return {
        id: ROOT_ID,
        label: '',
        kind: 'branch',
        searchPlaceholder: placeholder,
        getChildren: ({ query }) => {
            const rootNodes = rootNodesRef.current
            const trimmed = query.trim().toLowerCase()
            return {
                isLoading: false,
                nodes: trimmed
                    ? rootNodes.filter((node) => {
                          const searchableText = [
                              node.label,
                              node.description,
                              node.hint,
                              ...(node.searchableText ?? []),
                          ]
                              .filter(Boolean)
                              .map(String)
                              .join(' ')
                              .toLowerCase()
                          return searchableText.includes(trimmed)
                      })
                    : rootNodes,
            }
        },
    }
}

function getNodeChildren(node: FilterPickerNode, path: FilterPickerPath): FilterPickerNode[] {
    return node.getChildren?.({ query: '', path }).nodes ?? []
}

// Resolution walks the node tree by stable IDs. `getChildren` must be pure (see FilterPicker.types),
// so calling it here on every render is side-effect-free. A segment that no longer resolves stops the walk
// at the deepest valid prefix rather than collapsing to root — so an edit path like [property, operator]
// still lands on the property's value step when a category auto-advances (no operator node exists), and a
// partially-stale path lands as close as possible. Covered by useFilterPickerNavigation.test.
function resolvePath(rootNode: FilterPickerNode, path?: FilterPickerPath): FilterPickerNode[] {
    const stack = [rootNode]
    if (!path?.nodeIds.length) {
        return stack
    }

    let parent = rootNode
    for (const nodeId of path.nodeIds) {
        const parentPath = { nodeIds: stack.filter((node) => node.id !== ROOT_ID).map((node) => node.id) }
        const nextNode = getNodeChildren(parent, parentPath).find((candidate) => candidate.id === nodeId)
        if (!nextNode) {
            return stack
        }
        stack.push(nextNode)
        parent = nextNode
    }
    return stack
}

function resolveIds(rootNode: FilterPickerNode, path?: FilterPickerPath): string[] {
    return resolvePath(rootNode, path)
        .filter((node) => node.id !== ROOT_ID)
        .map((node) => node.id)
}

export interface UseFilterPickerNavigationProps {
    rootNodes: FilterPickerNode[]
    initialPath?: FilterPickerPath
    rootSearchPlaceholder?: string
    /** When provided, the hook re-applies `initialPath` each time `open` transitions to true. */
    open?: boolean
}

export interface UseFilterPickerNavigationResult {
    rootNode: FilterPickerNode
    stack: FilterPickerNode[]
    activeNode: FilterPickerNode
    activePath: FilterPickerPath
    query: string
    setQuery: (query: string) => void
    openNode: (node: FilterPickerNode) => void
    goBack: () => void
    resetToRoot: () => void
    resetToPath: (path?: FilterPickerPath) => void
    isRoot: boolean
}

export function useFilterPickerNavigation({
    rootNodes,
    initialPath,
    rootSearchPlaceholder,
    open = true,
}: UseFilterPickerNavigationProps): UseFilterPickerNavigationResult {
    const rootNodesRef = useRef(rootNodes)
    rootNodesRef.current = rootNodes

    const rootNode = useMemo(() => createRootNode(rootNodesRef, rootSearchPlaceholder), [rootSearchPlaceholder])
    const requestedPathKey = pathKey(initialPath)
    const initialPathRef = useRef(initialPath)
    initialPathRef.current = initialPath

    // `requestedNodeIds` is the single source of truth for navigation. Everything else (the resolved stack,
    // the active node, the active path) is derived from it against the current node tree, so the picker can
    // never hold a path that no longer resolves.
    const [requestedNodeIds, setRequestedNodeIds] = useState<string[]>(() =>
        resolveIds(rootNode, initialPathRef.current)
    )
    const [query, setQuery] = useState('')

    // Re-apply the requested edit path whenever the picker opens or the requested path changes. This is the
    // only place `open` drives navigation — the parent must not also reset, or the two owners race (the bug
    // that made token edits open at root). When closed we leave state untouched; the next open re-resolves.
    useEffect(() => {
        if (!open) {
            return
        }
        setQuery('')
        setRequestedNodeIds(resolveIds(rootNode, initialPathRef.current))
    }, [open, requestedPathKey, rootNode])

    // Resolution is cheap and pure, so it runs each render rather than being memoized: the node tree's
    // *content* (e.g. freshly loaded values) changes without the `rootNodes` array identity changing, so a
    // memo keyed on identity would serve stale nodes.
    const requestedPath = useMemo<FilterPickerPath>(() => ({ nodeIds: requestedNodeIds }), [requestedNodeIds])
    const stack = resolvePath(rootNode, requestedPath)
    const resolvedNodeIds = stack.filter((node) => node.id !== ROOT_ID).map((node) => node.id)
    // Use a control character (not `/`) as the dependency-key separator so node ids that themselves contain
    // `/` can't collide; the resolved array is returned verbatim rather than reconstructed by splitting.
    const resolvedKey = resolvedNodeIds.join('')

    // Navigation callbacks operate on the *resolved* ids (via a ref) so they always build off a path that
    // actually exists, even if `requestedNodeIds` still carries a now-stale tail.
    const resolvedNodeIdsRef = useRef(resolvedNodeIds)
    resolvedNodeIdsRef.current = resolvedNodeIds

    // Recompute only when the resolved path string changes; the ref holds the matching array, which keeps
    // activePath referentially stable across unrelated re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const activePath = useMemo<FilterPickerPath>(() => ({ nodeIds: resolvedNodeIdsRef.current }), [resolvedKey])

    const openNode = useCallback((node: FilterPickerNode): void => {
        setQuery('')
        setRequestedNodeIds([...resolvedNodeIdsRef.current, node.id])
    }, [])

    const goBack = useCallback((): void => {
        setQuery('')
        setRequestedNodeIds(resolvedNodeIdsRef.current.slice(0, -1))
    }, [])

    const resetToRoot = useCallback((): void => {
        setQuery('')
        setRequestedNodeIds([])
    }, [])

    const resetToPath = useCallback(
        (path?: FilterPickerPath): void => {
            setQuery('')
            setRequestedNodeIds(resolveIds(rootNode, path))
        },
        [rootNode]
    )

    const activeNode = stack[stack.length - 1]

    return {
        rootNode,
        stack,
        activeNode,
        activePath,
        query,
        setQuery,
        openNode,
        goBack,
        resetToRoot,
        resetToPath,
        isRoot: stack.length === 1,
    }
}
