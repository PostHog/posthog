import type { ThinkingLevel } from "@earendil-works/pi-agent-core";
import type {
  ExtensionError,
  RpcClient,
  RpcExtensionUIRequest,
  RpcSessionState,
} from "@earendil-works/pi-coding-agent";

export type {
  RpcExtensionUIRequest,
  RpcExtensionUIResponse,
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

export type PiExtensionError = ExtensionError & {
  type: "extension_error";
};

export type PiExtensionEvent = RpcExtensionUIRequest | PiExtensionError;

export type PiSessionStats = Awaited<ReturnType<RpcClient["getSessionStats"]>>;
