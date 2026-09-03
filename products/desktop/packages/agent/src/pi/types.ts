import type { ThinkingLevel } from "@earendil-works/pi-agent-core";
import type {
  ExtensionError,
  RpcClient,
  RpcExtensionUIRequest,
  RpcExtensionUIResponse,
  RpcSessionState,
} from "@earendil-works/pi-coding-agent";
import { z } from "zod";

export type {
  RpcExtensionUIRequest,
  RpcExtensionUIResponse,
} from "@earendil-works/pi-coding-agent";

function exhaustiveValues<T>() {
  return <const Values extends readonly T[]>(
    values: Values & ([T] extends [Values[number]] ? unknown : never),
  ): Values => values;
}

function exhaustiveRecord<T extends PropertyKey>() {
  return <const Values extends { [Key in T]: Key }>(values: Values): Values =>
    values;
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
export type PiExtensionSessionEvent = PiExtensionEvent | RpcExtensionUIResponse;

const extensionRequestBase = {
  type: z.literal("extension_ui_request"),
  id: z.string(),
};

const PI_EXTENSION_UI_METHODS = exhaustiveRecord<
  RpcExtensionUIRequest["method"]
>()({
  select: "select",
  confirm: "confirm",
  input: "input",
  editor: "editor",
  notify: "notify",
  setStatus: "setStatus",
  setWidget: "setWidget",
  setTitle: "setTitle",
  set_editor_text: "set_editor_text",
});

const piExtensionUIRequestSchema = z
  .discriminatedUnion("method", [
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.select),
      title: z.string(),
      options: z.array(z.string()),
      timeout: z.number().optional(),
    }),
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.confirm),
      title: z.string(),
      message: z.string(),
      timeout: z.number().optional(),
    }),
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.input),
      title: z.string(),
      placeholder: z.string().optional(),
      timeout: z.number().optional(),
    }),
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.editor),
      title: z.string(),
      prefill: z.string().optional(),
    }),
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.notify),
      message: z.string(),
      notifyType: z.enum(["info", "warning", "error"]).optional(),
    }),
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.setStatus),
      statusKey: z.string(),
      statusText: z.string().optional(),
    }),
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.setWidget),
      widgetKey: z.string(),
      widgetLines: z.array(z.string()).optional(),
      widgetPlacement: z.enum(["aboveEditor", "belowEditor"]).optional(),
    }),
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.setTitle),
      title: z.string(),
    }),
    z.looseObject({
      ...extensionRequestBase,
      method: z.literal(PI_EXTENSION_UI_METHODS.set_editor_text),
      text: z.string(),
    }),
  ])
  .transform((request): RpcExtensionUIRequest => {
    if (request.method === "setStatus") {
      return { ...request, statusText: request.statusText };
    }
    if (request.method === "setWidget") {
      return { ...request, widgetLines: request.widgetLines };
    }
    return request;
  });

const piExtensionErrorSchema = z.looseObject({
  type: z.literal("extension_error"),
  extensionPath: z.string(),
  event: z.string(),
  error: z.string(),
  stack: z.string().optional(),
});

export const piExtensionUIResponseSchema = z
  .union([
    z.looseObject({
      type: z.literal("extension_ui_response"),
      id: z.string(),
      value: z.string(),
    }),
    z.looseObject({
      type: z.literal("extension_ui_response"),
      id: z.string(),
      confirmed: z.boolean(),
    }),
    z.looseObject({
      type: z.literal("extension_ui_response"),
      id: z.string(),
      cancelled: z.literal(true),
    }),
  ])
  .transform((response): RpcExtensionUIResponse => response);

export const piExtensionEventSchema = z.union([
  piExtensionUIRequestSchema,
  piExtensionErrorSchema,
]);

export const piExtensionSessionEventSchema = z.union([
  piExtensionEventSchema,
  piExtensionUIResponseSchema,
]);

export type PiSessionStats = Awaited<ReturnType<RpcClient["getSessionStats"]>>;
