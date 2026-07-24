import type { QueueMode, ThinkingLevel } from "@earendil-works/pi-agent-core";
import type {
  RpcClient,
  RpcSessionState,
} from "@earendil-works/pi-coding-agent";

function exhaustiveValues<T>() {
  return <const Values extends readonly T[]>(
    values: Values & ([T] extends [Values[number]] ? unknown : never),
  ): Values => values;
}

export type PiThinkingLevel = ThinkingLevel;
export type PiQueueMode = QueueMode;

export const PI_THINKING_LEVELS = exhaustiveValues<PiThinkingLevel>()([
  "off",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
]);

export const PI_QUEUE_MODES = exhaustiveValues<PiQueueMode>()([
  "all",
  "one-at-a-time",
]);

export type PiNativeModelInfo = Awaited<
  ReturnType<RpcClient["getAvailableModels"]>
>[number];

export type PiModelOption = PiNativeModelInfo & {
  thinkingLevels: PiThinkingLevel[];
};

export type PiCommand = Awaited<ReturnType<RpcClient["getCommands"]>>[number];

export type PiSessionStatus = Omit<RpcSessionState, "model"> & {
  model?: Pick<NonNullable<RpcSessionState["model"]>, "provider" | "id">;
};

export type PiSessionStats = Awaited<ReturnType<RpcClient["getSessionStats"]>>;
