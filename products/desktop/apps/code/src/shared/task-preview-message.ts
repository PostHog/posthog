import { elementCommentAnchorSchema } from "@posthog/core/comments/anchors";
import type {
  TaskPreviewElement,
  TaskPreviewPin,
  TaskPreviewRect,
} from "@posthog/ui/features/task-preview/taskPreviewFrameHost";

export const TASK_PREVIEW_MAX_PINS = 200;
const MAX_ID_LENGTH = 128;
const MAX_PATH_LENGTH = 2_000;
const MAX_SELECTOR_LENGTH = 1_000;

const elementSchema = elementCommentAnchorSchema.omit({ kind: true });

export type TaskPreviewGuestMessage =
  | { type: "picked"; element: TaskPreviewElement; rect: TaskPreviewRect }
  | { type: "pick-cancelled" }
  | { type: "activate"; id: string };

export type TaskPreviewHostMessage =
  | { type: "pick"; active: boolean }
  | { type: "pins"; items: TaskPreviewPin[] }
  | { type: "locate"; id: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function boundedString(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length <= maxLength;
}

function boundedId(value: unknown): value is string {
  return boundedString(value, MAX_ID_LENGTH) && value.length > 0;
}

function finiteRect(value: unknown): TaskPreviewRect | null {
  if (!isRecord(value)) return null;
  const rect: Record<string, number> = {};
  for (const key of ["top", "left", "right", "bottom", "width", "height"]) {
    const field = value[key];
    if (typeof field !== "number" || !Number.isFinite(field)) return null;
    rect[key] = field;
  }
  return rect as TaskPreviewRect;
}

export function sanitizeTaskPreviewGuestMessage(
  value: unknown,
): TaskPreviewGuestMessage | null {
  if (!isRecord(value)) return null;
  if (value.type === "pick-cancelled") return { type: "pick-cancelled" };
  if (value.type === "activate" && boundedId(value.id)) {
    return { type: "activate", id: value.id };
  }
  if (value.type === "picked") {
    const element = elementSchema.safeParse(value.element);
    const rect = finiteRect(value.rect);
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
    !boundedString(value.path, MAX_PATH_LENGTH) ||
    !boundedString(value.selector, MAX_SELECTOR_LENGTH) ||
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
