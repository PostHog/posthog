export const THREAD_HOTKEY_OPTIONS = {
  enableOnFormTags: true,
  enableOnContentEditable: true,
  // The composer holds focus whenever a task is open, so thread shortcuts must fire from it
  // (`.cli-editor` is its ProseMirror root) and from the jump picker itself; every other editable
  // surface keeps its keys — alt+arrows move lines in CodeMirror, ctrl+j is a newline in terminals.
  ignoreEventWhen: (event: KeyboardEvent) => {
    const target = event.target;
    if (!(target instanceof Element)) return false;
    const editable = target.closest(
      'input, textarea, [contenteditable="true"], [contenteditable=""], [contenteditable="plaintext-only"]',
    );
    if (!editable) return false;
    return target.closest(".cli-editor, [data-message-jump-picker]") === null;
  },
  preventDefault: true,
} as const;
