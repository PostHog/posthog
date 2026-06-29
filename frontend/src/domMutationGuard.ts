/**
 * Hardens React reconciliation against browser extensions that mutate the DOM out from under React.
 *
 * Extensions such as Google Translate, ad blockers, and "dark mode" injectors relocate or delete
 * text nodes that React still holds a reference to. During React's commit phase this turns into a
 * call to `removeChild` / `insertBefore` with a node that is no longer a child of the expected
 * parent, and the browser throws `NotFoundError: Failed to execute 'removeChild' on 'Node'`
 * (or the `insertBefore` equivalent). That exception escapes into the reconciler and tears down the
 * surrounding subtree — on the Web analytics dashboard it leaves the page stuck behind an error box.
 *
 * These guards make the two methods a no-op — returning the node, exactly as a successful spec call
 * would — when the node isn't actually a child of `this`. The extension-induced mismatch then can't
 * crash the app. This is the well-known Node-prototype workaround for the React + extension
 * interaction (see facebook/react#11538).
 */

const PATCH_FLAG = '__phDomMutationGuarded'

export function patchDomMutationMethodsForExtensions(): void {
    if (typeof Node !== 'function' || !Node.prototype) {
        return
    }

    const proto = Node.prototype as Node & Record<string, unknown>
    if (proto[PATCH_FLAG]) {
        return
    }
    proto[PATCH_FLAG] = true

    const originalRemoveChild = Node.prototype.removeChild
    Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
        if (child.parentNode !== this) {
            return child
        }
        return originalRemoveChild.call(this, child) as T
    }

    const originalInsertBefore = Node.prototype.insertBefore
    Node.prototype.insertBefore = function <T extends Node>(this: Node, newNode: T, referenceNode: Node | null): T {
        if (referenceNode && referenceNode.parentNode !== this) {
            return newNode
        }
        return originalInsertBefore.call(this, newNode, referenceNode) as T
    }
}
