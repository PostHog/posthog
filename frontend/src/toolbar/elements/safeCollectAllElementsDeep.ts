// Replacement for `collectAllElementsDeep('*', document)` from query-selector-shadow-dom.
// Reading `.shadowRoot` on a cross-origin iframe element can throw a SecurityError; the
// library doesn't guard the access, so a single iframe would tear down the toolbar overlay.
// This helper isolates the unsafe read per element.

function safeShadowRoot(element: Element): ShadowRoot | null {
    try {
        return element.shadowRoot
    } catch {
        return null
    }
}

export function safeCollectAllElementsDeep(root: Document | ShadowRoot = document): HTMLElement[] {
    const collected: HTMLElement[] = []
    const stack: (Document | ShadowRoot)[] = [root]

    while (stack.length) {
        const node = stack.pop() as Document | ShadowRoot
        let children: NodeListOf<Element>
        try {
            children = node.querySelectorAll('*')
        } catch {
            continue
        }
        for (let i = 0; i < children.length; i++) {
            const el = children[i] as HTMLElement
            collected.push(el)
            const shadow = safeShadowRoot(el)
            if (shadow) {
                stack.push(shadow)
            }
        }
    }
    return collected
}
