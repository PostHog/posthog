// Page-translation extensions (Chrome's built-in "Translate this page", Google Translate, and
// similar) rewrite text nodes in place: they wrap a text node in a <font> element and reparent
// it. React keeps its own reference to the original node. When React later commits an update, it
// calls parent.insertBefore(node, referenceNode) or parent.removeChild(child) against a DOM that
// no longer matches its tree, and the browser throws NotFoundError. React cannot catch this, so
// the whole subtree unmounts to the nearest error boundary — a full-page crash the user cannot
// retry past.
//
// These overrides only change behaviour in the exact case that would otherwise throw: when the
// reference/child node is not a child of the node the operation runs on. A correct call is passed
// straight through, so this cannot mask a working operation. React recovers on its next render.

let installed = false

export function installDOMTranslationResilience(): void {
    if (installed || typeof Node !== 'function' || !Node.prototype) {
        return
    }
    installed = true

    const originalInsertBefore = Node.prototype.insertBefore
    Node.prototype.insertBefore = function <T extends Node>(this: Node, newNode: T, referenceNode: Node | null): T {
        if (referenceNode && referenceNode.parentNode !== this) {
            // The reference node was reparented (e.g. wrapped in a <font> by a translator).
            // Appending keeps newNode in the tree instead of throwing and losing the commit.
            return this.appendChild(newNode)
        }
        return originalInsertBefore.call(this, newNode, referenceNode) as T
    }

    const originalRemoveChild = Node.prototype.removeChild
    Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
        if (child.parentNode !== this) {
            // The node was already detached or reparented by a translator; the removal React
            // wanted has effectively happened, so treat it as a no-op instead of throwing.
            return child
        }
        return originalRemoveChild.call(this, child) as T
    }
}
