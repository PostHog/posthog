import type {
  PiExtensionEvent,
  RpcExtensionUIRequest,
} from "@posthog/agent/pi/types";
import { createStore, type StoreApi } from "zustand/vanilla";

export type PiExtensionDialogRequest = Extract<
  RpcExtensionUIRequest,
  { method: "select" | "confirm" | "input" | "editor" }
>;

type PiExtensionNotifyRequest = Extract<
  RpcExtensionUIRequest,
  { method: "notify" }
>;

export type PiExtensionNotification = Pick<
  PiExtensionNotifyRequest,
  "id" | "message"
> & {
  notifyType: NonNullable<PiExtensionNotifyRequest["notifyType"]>;
};

type PiExtensionWidgetRequest = Extract<
  RpcExtensionUIRequest,
  { method: "setWidget" }
>;

export interface PiExtensionWidget {
  lines: NonNullable<PiExtensionWidgetRequest["widgetLines"]>;
  placement: NonNullable<PiExtensionWidgetRequest["widgetPlacement"]>;
}

type PiExtensionEditorTextRequest = Extract<
  RpcExtensionUIRequest,
  { method: "set_editor_text" }
>;

export type PiExtensionEditorText = Pick<
  PiExtensionEditorTextRequest,
  "id" | "text"
>;

export interface PiExtensionTaskState {
  dialogs: PiExtensionDialogRequest[];
  notifications: PiExtensionNotification[];
  statuses: Record<string, string>;
  widgets: Record<string, PiExtensionWidget>;
  title?: string;
  editorText?: PiExtensionEditorText;
}

export interface PiExtensionState {
  tasks: Record<string, PiExtensionTaskState>;
}

export type PiExtensionStore = StoreApi<PiExtensionState>;

export type PiExtensionStateAction =
  | { type: "event"; event: PiExtensionEvent; id: string }
  | { type: "notification"; notification: PiExtensionNotification }
  | { type: "remove-dialog"; id: string }
  | { type: "remove-notification"; id: string }
  | { type: "consume-editor-text"; id: string };

export function createEmptyPiExtensionTaskState(): PiExtensionTaskState {
  return {
    dialogs: [],
    notifications: [],
    statuses: {},
    widgets: {},
  };
}

export function reducePiExtensionState(
  state: PiExtensionTaskState,
  action: PiExtensionStateAction,
): PiExtensionTaskState {
  if (action.type === "notification") {
    return addNotification(state, action.notification);
  }
  if (action.type === "remove-dialog") {
    return {
      ...state,
      dialogs: state.dialogs.filter((dialog) => dialog.id !== action.id),
    };
  }
  if (action.type === "remove-notification") {
    return {
      ...state,
      notifications: state.notifications.filter(
        (notification) => notification.id !== action.id,
      ),
    };
  }
  if (action.type === "consume-editor-text") {
    return state.editorText?.id === action.id
      ? { ...state, editorText: undefined }
      : state;
  }

  const event = action.event;
  if (event.type === "extension_error") {
    const extensionName = event.extensionPath.split(/[\\/]/).pop();
    return addNotification(state, {
      id: action.id,
      message: `${extensionName ?? event.extensionPath} failed during ${event.event}: ${event.error}`,
      notifyType: "error",
    });
  }

  switch (event.method) {
    case "select":
    case "confirm":
    case "input":
    case "editor":
      return state.dialogs.some((dialog) => dialog.id === event.id)
        ? state
        : { ...state, dialogs: [...state.dialogs, event] };
    case "notify":
      return addNotification(state, {
        id: event.id,
        message: event.message,
        notifyType: event.notifyType ?? "info",
      });
    case "setStatus": {
      const statuses = { ...state.statuses };
      if (event.statusText === undefined) {
        delete statuses[event.statusKey];
      } else {
        statuses[event.statusKey] = event.statusText;
      }
      return { ...state, statuses };
    }
    case "setWidget": {
      const widgets = { ...state.widgets };
      if (event.widgetLines === undefined) {
        delete widgets[event.widgetKey];
      } else {
        widgets[event.widgetKey] = {
          lines: event.widgetLines,
          placement: event.widgetPlacement ?? "aboveEditor",
        };
      }
      return { ...state, widgets };
    }
    case "setTitle":
      return { ...state, title: event.title };
    case "set_editor_text":
      return {
        ...state,
        editorText: { id: event.id, text: event.text },
      };
  }
}

function addNotification(
  state: PiExtensionTaskState,
  notification: PiExtensionNotification,
): PiExtensionTaskState {
  return {
    ...state,
    notifications: [
      ...state.notifications.filter(({ id }) => id !== notification.id),
      notification,
    ],
  };
}

export function createPiExtensionStore(): PiExtensionStore {
  return createStore<PiExtensionState>(() => ({ tasks: {} }));
}
