import { GITHUB_REF_URL_ATTR } from "@posthog/ui/features/editor/components/GithubRefChip";

/**
 * Resolve the GitHub PR/issue URL the context menu was opened on, if the
 * right-click landed inside a {@link GithubRefChip}. Returns `null` for any
 * other target (prose, file chips, empty space, non-elements).
 */
export function getGithubRefUrlFromEventTarget(
  target: EventTarget | null,
): string | null {
  // `Element`, not `HTMLElement`: the chip icon renders as an <svg>, whose
  // right-click target is an SVGElement that still supports `closest()`.
  if (!(target instanceof Element)) return null;
  return (
    target
      .closest(`[${GITHUB_REF_URL_ATTR}]`)
      ?.getAttribute(GITHUB_REF_URL_ATTR) ?? null
  );
}

/**
 * The selected text when the selection reaches into `container`, else `null`.
 *
 * Lets a context menu inside a message copy what the reader highlighted rather
 * than the whole message, matching what right-clicking a selection does
 * everywhere else. Read it on the `contextmenu` event: once the menu opens it
 * owns focus, and the selection is no longer reliable.
 *
 * Intersection, not containment — a selection dragged across several messages
 * still copies whole from a right-click on any one of them.
 */
export function getSelectionWithin(container: Node | null): string | null {
  if (!container) return null;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return null;
  const text = selection.toString();
  if (!text.trim()) return null;
  for (let i = 0; i < selection.rangeCount; i++) {
    if (selection.getRangeAt(i).intersectsNode(container)) return text;
  }
  return null;
}

/**
 * Copy text to the clipboard from a context-menu selection.
 *
 * The write is deferred to a later task on purpose. When a Radix
 * `ContextMenu.Item` is selected, the menu's focus scope is being torn down and
 * the document is momentarily not focused — calling `navigator.clipboard.writeText`
 * synchronously there rejects with "Document is not focused" in Electron/Chromium,
 * so the clipboard is left unchanged. Deferring lets the menu finish closing and
 * focus return to the document before we write.
 */
export function copyFromContextMenu(
  text: string,
  callbacks: { onSuccess?: () => void; onError?: () => void } = {},
): void {
  setTimeout(() => {
    navigator.clipboard
      .writeText(text)
      .then(() => callbacks.onSuccess?.())
      .catch(() => callbacks.onError?.());
  }, 0);
}
