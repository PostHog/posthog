export function scrollParentOf(element: Element): HTMLElement | null {
    for (let node = element.parentElement; node; node = node.parentElement) {
        const { overflowY } = getComputedStyle(node)
        if (overflowY === 'auto' || overflowY === 'scroll') {
            return node
        }
    }
    return null
}
