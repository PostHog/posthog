const EDITOR_CLASS =
  "cli-editor min-h-[1.5em] w-full break-words border-none bg-transparent pr-2 text-[14px] text-[var(--gray-12)] outline-none [overflow-wrap:break-word] [white-space:pre-wrap] [word-break:break-word]";

export function getPromptEditorAttributes(): Record<string, string> {
  return { class: EDITOR_CLASS, spellcheck: "true" };
}
