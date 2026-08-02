import type { ThinkingLevel } from "@earendil-works/pi-agent-core";
import type {
  RpcClient,
  RpcExtensionUIRequest,
  RpcExtensionUIResponse,
  RpcSessionState,
} from "@earendil-works/pi-coding-agent";

function exhaustiveValues<T>() {
  return <const Values extends readonly T[]>(
    values: Values & ([T] extends [Values[number]] ? unknown : never),
  ): Values => values;
}

export type PiThinkingLevel = ThinkingLevel;

export const PI_THINKING_LEVELS = exhaustiveValues<PiThinkingLevel>()([
  "off",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
]);

export type PiNativeModelInfo = Awaited<
  ReturnType<RpcClient["getAvailableModels"]>
>[number];

export interface PiPersistedSessionConfig {
  model: { provider: string; id: string } | null;
  thinkingLevel: PiThinkingLevel;
}

export type PiCommand = Awaited<ReturnType<RpcClient["getCommands"]>>[number];

export type PiSessionStatus = Omit<RpcSessionState, "model"> & {
  model?: Pick<NonNullable<RpcSessionState["model"]>, "provider" | "id">;
};

export interface PiQueueSnapshot {
  steering: string[];
  followUp: string[];
}

export type PiExtensionUIRequest = RpcExtensionUIRequest;
export type PiExtensionUIResponse = RpcExtensionUIResponse;

export interface PiExtensionError {
  type: "extension_error";
  extensionPath: string;
  event: string;
  error: string;
}

export interface PiExtensionSessionReset {
  type: "extension_session_reset";
}

export interface PiExtensionDialogExpired {
  type: "extension_dialog_expired";
  id: string;
}

export interface PiExtensionStateSnapshot {
  type: "extension_state_snapshot";
  dialogs: Array<
    Extract<
      PiExtensionUIRequest,
      { method: "select" | "confirm" | "input" | "editor" }
    >
  >;
  statuses: Array<Extract<PiExtensionUIRequest, { method: "setStatus" }>>;
  widgets: Array<Extract<PiExtensionUIRequest, { method: "setWidget" }>>;
  title?: Extract<PiExtensionUIRequest, { method: "setTitle" }>;
  editorText?: Extract<PiExtensionUIRequest, { method: "set_editor_text" }>;
}

export type PiExtensionWireEvent = PiExtensionUIRequest | PiExtensionError;
export type PiExtensionEvent =
  | PiExtensionWireEvent
  | PiExtensionSessionReset
  | PiExtensionDialogExpired
  | PiExtensionStateSnapshot;

export type PiSessionStats = Awaited<ReturnType<RpcClient["getSessionStats"]>>;
