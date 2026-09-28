import {
  findText,
  focus,
  focusedForm,
  type PageKit,
  pageKit,
  rect,
  sensitivity,
  snapshot,
} from "./page-runtime.js";

export const PAGE_WORLD_ID = 1717;

function script<A>(fn: (kit: PageKit, args: A) => unknown, args: A): string {
  return `(${fn})((${pageKit})(), ${JSON.stringify(args)})`;
}

export function snapshotScript(maxChars: number): string {
  return script(snapshot, { maxChars });
}

export function rectScript(ref: string, forClick = false): string {
  return script(rect, { ref, forClick });
}

export function focusScript(ref: string, clear: boolean): string {
  return script(focus, { ref, clear });
}

export function findTextScript(text: string): string {
  return script(findText, { text });
}

export function sensitivityScript(ref: string): string {
  return script(sensitivity, { ref });
}

export function focusedFormScript(): string {
  return script(focusedForm, {});
}

export function evaluateScript(source: string): string {
  return `(async () => { const fn = (${source}); const value = await (typeof fn === "function" ? fn() : fn); return JSON.parse(JSON.stringify(value ?? null)); })()`;
}
