import type { KeyboardEvent } from "react";

const STEP_BY_KEY: Record<string, number> = {
  ArrowDown: 1,
  j: 1,
  ArrowUp: -1,
  k: -1,
};

function threadListStops(from: HTMLElement, selector: string): HTMLElement[] {
  const list = from.closest("[data-comment-thread-list]");
  return list ? [...list.querySelectorAll<HTMLElement>(selector)] : [];
}

export function adjacentThread(from: HTMLElement): HTMLElement | null {
  const threads = threadListStops(from, '[data-thread-focus="thread"]');
  const index = threads.indexOf(from);
  return threads[index + 1] ?? threads[index - 1] ?? null;
}

export function moveThreadFocus(event: KeyboardEvent<HTMLElement>): void {
  const step = STEP_BY_KEY[event.key];
  if (!step || event.metaKey || event.ctrlKey || event.altKey) return;
  const stops = threadListStops(event.currentTarget, "[data-thread-focus]");
  const next = stops[stops.indexOf(event.currentTarget) + step];
  if (!next) return;
  event.preventDefault();
  next.focus();
  next.scrollIntoView?.({ block: "nearest" });
}
