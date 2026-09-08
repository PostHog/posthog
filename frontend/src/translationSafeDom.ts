interface Capturable {
    capture: (event: string, properties?: Record<string, unknown>) => void
}

let restoreNativeMutators: (() => void) | null = null

function looksTranslated(): boolean {
    // Chromium's built-in translation and the Google Translate widget both mark <html>. Firefox
    // and Yandex leave no marker, so an absent class does not mean translation is off.
    const classes = document.documentElement.classList
    return classes.contains('translated-ltr') || classes.contains('translated-rtl')
}

/**
 * Make React's commit phase survive a page whose text was rewritten below it.
 *
 * Every shipping in-page translator (Chrome, Edge, Firefox and Yandex built-ins, the Google
 * Translate widget, translation extensions) translates a page by replacing bare text nodes with
 * `<font>` wrappers. React keeps the original text node in its fiber tree, so the next commit
 * that removes or reorders that text calls `removeChild` or `insertBefore` for a node the
 * document no longer parents, and the DOM throws `NotFoundError`. A throw in the commit phase
 * is not recoverable, so React unwinds to the nearest error boundary and the fallback replaces
 * the whole subtree. See facebook/react#11538.
 *
 * The two wrappers below are different from the native methods only in the case that throws: a
 * node that is not a child becomes a no-op, and a reference node with a different parent
 * becomes an append. Both can leave a translated node on screen that React thinks it removed.
 * A stale line of text is much better than the loss of the scene the person works in.
 *
 * Returns a function that puts the native methods back.
 */
export function installTranslationSafeDom(posthog?: Capturable): () => void {
    if (restoreNativeMutators) {
        return () => {}
    }

    const nativeRemoveChild = Node.prototype.removeChild
    const nativeInsertBefore = Node.prototype.insertBefore

    // A translated page trips this on most commits, so report the first one per page load only.
    let reported = false
    function report(operation: string, node: Node): void {
        if (reported) {
            return
        }
        reported = true
        posthog?.capture('translation_safe_dom_guarded', {
            operation,
            node_name: node.nodeName,
            document_translated: looksTranslated(),
            html_lang: document.documentElement.lang || null,
            current_path: window.location.pathname,
        })
    }

    Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
        if (child.parentNode !== this) {
            report('removeChild', child)
            return child
        }
        return nativeRemoveChild.call(this, child) as T
    }

    Node.prototype.insertBefore = function <T extends Node>(this: Node, node: T, child: Node | null): T {
        if (child && child.parentNode !== this) {
            report('insertBefore', node)
            return nativeInsertBefore.call(this, node, null) as T
        }
        return nativeInsertBefore.call(this, node, child) as T
    }

    restoreNativeMutators = () => {
        Node.prototype.removeChild = nativeRemoveChild
        Node.prototype.insertBefore = nativeInsertBefore
        restoreNativeMutators = null
    }
    return restoreNativeMutators
}
