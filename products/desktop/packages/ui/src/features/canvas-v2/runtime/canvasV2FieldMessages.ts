import {
  CANVAS_V2_FIELD_MARK,
  isField,
  materializeList,
  materializeText,
} from "@posthog/shared";

export interface CanvasV2TextMessage {
  __text: string;
  ids: string[];
}

export interface CanvasV2ListMessage {
  __list: { id: string; value: unknown }[];
}

/** What the frame receives for one state key. A field goes over materialized. */
export function fieldMessageValue(value: unknown): unknown {
  if (!isField(value)) return value;
  if (value[CANVAS_V2_FIELD_MARK] === "text") {
    const view = materializeText(value);
    const message: CanvasV2TextMessage = { __text: view.text, ids: view.ids };
    return message;
  }
  const message: CanvasV2ListMessage = { __list: materializeList(value) };
  return message;
}

/** What a plain reader gets: the string, or the values of the list. */
export function fieldPlainValue(value: unknown): unknown {
  if (!isField(value)) return value;
  if (value[CANVAS_V2_FIELD_MARK] === "text") {
    return materializeText(value).text;
  }
  return materializeList(value).map((row) => row.value);
}
