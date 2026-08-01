import type { MouseEvent } from "react";

const INTERACTIVE_SELECTOR =
  'button, a, input, textarea, select, [role="button"], [role="link"], [contenteditable="true"], [data-interactive]';

export function focusComposerOnPaneClick(
  event: Pick<MouseEvent, "target">,
  focusComposer: () => void,
): void {
  const target = event.target;
  if (!(target instanceof Element) || target.closest(INTERACTIVE_SELECTOR)) {
    return;
  }

  const selection = window.getSelection();
  if (selection && selection.toString().length > 0) {
    return;
  }

  focusComposer();
}
