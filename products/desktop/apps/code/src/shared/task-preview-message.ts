import {
  ELEMENT_ANCHOR_LIMITS,
  elementCommentAnchorSchema,
} from "@posthog/core/comments/anchors";
import type {
  TaskPreviewElement,
  TaskPreviewPin,
  TaskPreviewRect,
} from "@posthog/ui/features/task-preview/taskPreviewFrameHost";
import { boundedString, finiteRect, isRecord } from "./bridge-guards";

export const TASK_PREVIEW_MAX_PINS = 200;
const MAX_ID_LENGTH = 128;

const elementSchema = elementCommentAnchorSchema.omit({ kind: true });

export type TaskPreviewGuestMessage =
  | { type: "picked"; element: TaskPreviewElement; rect: TaskPreviewRect }
  | { type: "pick-cancelled" }
  | { type: "activate"; id: string }
  | { type: "pins-changed"; ids: string[] };

export type TaskPreviewHostMessage =
  | { type: "pick"; active: boolean }
  | { type: "pins"; items: TaskPreviewPin[] }
  | { type: "locate"; id: string }
  | { type: "release" };

function boundedId(value: unknown): value is string {
  return boundedString(value, MAX_ID_LENGTH) && value.length > 0;
}

export function sanitizeTaskPreviewGuestMessage(
  value: unknown,
): TaskPreviewGuestMessage | null {
  if (!isRecord(value)) return null;
  if (value.type === "pick-cancelled") return { type: "pick-cancelled" };
  if (value.type === "activate" && boundedId(value.id)) {
    return { type: "activate", id: value.id };
  }
  if (value.type === "pins-changed" && Array.isArray(value.ids)) {
    if (value.ids.length > TASK_PREVIEW_MAX_PINS) return null;
    return value.ids.every(boundedId)
      ? { type: "pins-changed", ids: value.ids as string[] }
      : null;
  }
  if (value.type === "picked") {
    const element = elementSchema.safeParse(value.element);
    const rect = finiteRect(value.rect) as TaskPreviewRect | null;
    return element.success && rect
      ? { type: "picked", element: element.data, rect }
      : null;
  }
  return null;
}

function sanitizePin(value: unknown): TaskPreviewPin | null {
  if (
    !isRecord(value) ||
    !boundedId(value.id) ||
    !boundedString(value.path, ELEMENT_ANCHOR_LIMITS.path) ||
    !boundedString(value.selector, ELEMENT_ANCHOR_LIMITS.selector) ||
    !boundedString(value.text, ELEMENT_ANCHOR_LIMITS.text) ||
    typeof value.number !== "number" ||
    !Number.isInteger(value.number) ||
    typeof value.active !== "boolean"
  ) {
    return null;
  }
  return {
    id: value.id,
    number: value.number,
    path: value.path,
    selector: value.selector,
    text: value.text,
    active: value.active,
  };
}

export function sanitizeTaskPreviewHostMessage(
  value: unknown,
): TaskPreviewHostMessage | null {
  if (!isRecord(value)) return null;
  if (value.type === "pick" && typeof value.active === "boolean") {
    return { type: "pick", active: value.active };
  }
  if (value.type === "release") return { type: "release" };
  if (value.type === "locate" && boundedId(value.id)) {
    return { type: "locate", id: value.id };
  }
  if (value.type === "pins" && Array.isArray(value.items)) {
    if (value.items.length > TASK_PREVIEW_MAX_PINS) return null;
    const items = value.items.map(sanitizePin);
    return items.every((item) => item !== null)
      ? { type: "pins", items: items as TaskPreviewPin[] }
      : null;
  }
  return null;
}
