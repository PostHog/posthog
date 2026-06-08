// Shared monaco-editor portal div for popups (tooltips, suggestion list,
// etc). Monaco's global services (HoverService, ContextView) register
// DomListeners against whatever node we hand them as overflowWidgetsDomNode
// and never release those listeners across editor disposals because the
// services themselves are module-level singletons (lazy-init via
// GlobalIdleValue). If we create a fresh div per editor and remove it on
// unmount, the singletons retain the detached div forever.
//
// Solution: one shared, never-removed div for every editor instance. The
// DomListeners stay bound to a div that's always attached, so nothing
// leaks. The `data-attr="monaco-overflow-root"` lets memlab/playwright
// assert there is exactly one of these on body no matter how many editors
// mount or unmount.

let sharedMonacoOverflowRootEl: HTMLDivElement | null = null

export function sharedMonacoOverflowRoot(): HTMLDivElement | undefined {
    if (typeof document === 'undefined') {
        return undefined
    }
    if (sharedMonacoOverflowRootEl && document.body.contains(sharedMonacoOverflowRootEl)) {
        return sharedMonacoOverflowRootEl
    }
    sharedMonacoOverflowRootEl = document.createElement('div')
    sharedMonacoOverflowRootEl.classList.add('monaco-editor')
    sharedMonacoOverflowRootEl.style.zIndex = 'var(--z-tooltip)'
    sharedMonacoOverflowRootEl.setAttribute('data-attr', 'monaco-overflow-root')
    document.body.appendChild(sharedMonacoOverflowRootEl)
    return sharedMonacoOverflowRootEl
}

export function _resetSharedMonacoOverflowRootForTests(): void {
    if (sharedMonacoOverflowRootEl && document.body.contains(sharedMonacoOverflowRootEl)) {
        sharedMonacoOverflowRootEl.remove()
    }
    sharedMonacoOverflowRootEl = null
}
