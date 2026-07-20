let guardInstalled = false

/**
 * Guards against crashes caused by DOM-mutating browser extensions (Google Translate and
 * similar translation/ad-blocking tools). Such extensions rewrite text nodes and move DOM
 * subtrees out from under React. When React's reconciler later runs removeChild/insertBefore
 * on a node whose parent the extension already changed, the browser throws a NotFoundError
 * ("The node to be removed is not a child of this node") during render, which tears down the
 * whole scene tree and locks affected users out of the page.
 *
 * We wrap the two prototype methods so that when the node isn't actually a child of the
 * expected parent, the call no-ops (returning the node) instead of throwing. This is the
 * well-known React + browser-extension mitigation; the extension-warning banner in
 * ErrorBoundary remains as a backstop for anything that still slips through.
 */
export function installDOMExtensionGuard(): void {
    if (guardInstalled || typeof Node !== 'function' || !Node.prototype) {
        return
    }
    guardInstalled = true

    const originalRemoveChild = Node.prototype.removeChild
    Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
        if (child.parentNode !== this) {
            // The extension already detached/moved this node; removing it would throw.
            return child
        }
        return originalRemoveChild.call(this, child) as T
    }

    const originalInsertBefore = Node.prototype.insertBefore
    Node.prototype.insertBefore = function <T extends Node>(this: Node, newNode: T, referenceNode: Node | null): T {
        if (referenceNode && referenceNode.parentNode !== this) {
            // The reference node was moved by the extension; fall back to appending so we
            // still insert the node instead of throwing.
            return originalInsertBefore.call(this, newNode, null) as T
        }
        return originalInsertBefore.call(this, newNode, referenceNode) as T
    }
}
