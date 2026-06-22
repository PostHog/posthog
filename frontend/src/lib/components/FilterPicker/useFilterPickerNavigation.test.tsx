import { act, renderHook } from '@testing-library/react'

import { FilterPickerNode } from './FilterPicker.types'
import { useFilterPickerNavigation } from './useFilterPickerNavigation'

const leaf: FilterPickerNode = { id: 'leaf', label: 'Leaf', kind: 'action' }
const branch: FilterPickerNode = {
    id: 'branch',
    label: 'Branch',
    kind: 'branch',
    getChildren: () => ({ nodes: [leaf], isLoading: false }),
}
const rootNodes: FilterPickerNode[] = [branch]

describe('useFilterPickerNavigation', () => {
    it('resolves initial paths and falls back to the deepest valid prefix when a segment is missing', () => {
        const { result, rerender } = renderHook(
            ({ initialPath }) => useFilterPickerNavigation({ rootNodes, initialPath }),
            { initialProps: { initialPath: { nodeIds: ['branch', 'leaf'] } } }
        )

        expect(result.current.activePath.nodeIds).toEqual(['branch', 'leaf'])
        expect(result.current.activeNode.id).toBe('leaf')

        // 'branch' resolves but 'missing' does not, so the walk stops at 'branch' rather than collapsing to root.
        rerender({ initialPath: { nodeIds: ['branch', 'missing'] } })

        expect(result.current.activePath.nodeIds).toEqual(['branch'])
        expect(result.current.activeNode.id).toBe('branch')
    })

    it('does not reset the stack on root node array identity churn', () => {
        const { result, rerender } = renderHook(({ nodes }) => useFilterPickerNavigation({ rootNodes: nodes }), {
            initialProps: { nodes: rootNodes },
        })

        act(() => result.current.openNode(branch))
        expect(result.current.activePath.nodeIds).toEqual(['branch'])

        rerender({ nodes: [...rootNodes] })

        expect(result.current.activePath.nodeIds).toEqual(['branch'])
    })

    it('keeps the active path but refreshes node data when root nodes change', () => {
        const updatedBranch: FilterPickerNode = { ...branch, label: 'Updated branch' }
        const { result, rerender } = renderHook(({ nodes }) => useFilterPickerNavigation({ rootNodes: nodes }), {
            initialProps: { nodes: rootNodes },
        })

        act(() => result.current.openNode(branch))
        rerender({ nodes: [updatedBranch] })

        expect(result.current.activePath.nodeIds).toEqual(['branch'])
        expect(result.current.activeNode.label).toBe('Updated branch')
    })

    it('falls back to the nearest valid path when an active node disappears', () => {
        const { result, rerender } = renderHook(({ nodes }) => useFilterPickerNavigation({ rootNodes: nodes }), {
            initialProps: { nodes: rootNodes },
        })

        act(() => result.current.openNode(branch))
        rerender({ nodes: [] })

        expect(result.current.activePath.nodeIds).toEqual([])
        expect(result.current.isRoot).toBe(true)
    })

    it('clears query when navigating back or resetting to root', () => {
        const { result } = renderHook(() => useFilterPickerNavigation({ rootNodes }))

        act(() => {
            result.current.setQuery('status')
            result.current.openNode(branch)
        })
        expect(result.current.query).toBe('')

        act(() => result.current.setQuery('active'))
        expect(result.current.query).toBe('active')

        act(() => result.current.goBack())
        expect(result.current.query).toBe('')
        expect(result.current.isRoot).toBe(true)

        act(() => {
            result.current.openNode(branch)
            result.current.setQuery('active')
            result.current.resetToRoot()
        })
        expect(result.current.query).toBe('')
        expect(result.current.isRoot).toBe(true)
    })

    it('can re-apply an edit path after resetting to root', () => {
        const { result } = renderHook(() => useFilterPickerNavigation({ rootNodes }))

        act(() => result.current.resetToRoot())
        expect(result.current.isRoot).toBe(true)

        act(() => result.current.resetToPath({ nodeIds: ['branch', 'leaf'] }))

        expect(result.current.activePath.nodeIds).toEqual(['branch', 'leaf'])
        expect(result.current.activeNode.id).toBe('leaf')
    })
})
