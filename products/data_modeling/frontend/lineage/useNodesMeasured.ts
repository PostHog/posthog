import { useStore } from '@xyflow/react'

/**
 * Whether react-flow has measured every node it currently holds.
 *
 * react-flow resolves a queued `fitView` as soon as the first node reports its size, which centers
 * the viewport on that one node and never corrects itself. Gate a fit on this hook, and keep it in
 * the effect dependencies so the fit runs again once the whole graph is measured.
 */
export function useNodesMeasured(): boolean {
    return useStore(
        (state) =>
            state.nodeLookup.size > 0 &&
            [...state.nodeLookup.values()].every((node) => node.measured.width && node.measured.height)
    )
}
