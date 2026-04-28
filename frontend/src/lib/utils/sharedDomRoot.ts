import { ReactNode } from 'react'
import { Root, createRoot } from 'react-dom/client'

export interface SharedDomRoot {
    element: HTMLElement | null
    root: Root | null
    owner: string | null
}

export interface SharedDomRootConfig {
    elementId: string
    setupElement: (element: HTMLElement) => void
}

export function createSharedDomRoot(): SharedDomRoot {
    return { element: null, root: null, owner: null }
}

export function ensureSharedDomRoot(target: SharedDomRoot, config: SharedDomRootConfig): [Root, HTMLElement] {
    if (target.root && target.element) {
        return [target.root, target.element]
    }
    const element = document.createElement('div')
    element.id = config.elementId
    config.setupElement(element)
    document.body.appendChild(element)
    const root = createRoot(element)
    target.element = element
    target.root = root
    return [root, element]
}

export function createOwnedRender(target: SharedDomRoot, ownerId: string): Root {
    return {
        render: (children: ReactNode): void => {
            if (target.owner !== ownerId || !target.root) {
                return
            }
            target.root.render(children)
        },
        unmount: (): void => {
            // shared root is never unmounted by callers; use resetSharedDomRoot for that
        },
    }
}

export function resetSharedDomRoot(target: SharedDomRoot): void {
    target.root?.unmount()
    target.element?.remove()
    target.element = null
    target.root = null
    target.owner = null
}
