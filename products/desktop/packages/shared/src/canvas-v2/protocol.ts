import { z } from "zod";
import { canvasV2FragmentSchema } from "./schemas";

export const CANVAS_V2_CHANNEL = "posthog-canvas-v2";

export const CANVAS_V2_FRAME_NAME = "posthog-canvas-board";
export const CANVAS_V2_BOARD_PARTITION = "canvas-board";
export const CANVAS_V2_BOARD_URL = "posthog-canvas://board/";
export const CANVAS_V2_FRAME_TO_HOST_CHANNEL = "posthog-canvas-frame";
export const CANVAS_V2_HOST_TO_FRAME_CHANNEL = "posthog-canvas-host";
export const CANVAS_V2_FROM_HOST_FLAG = "__phFromHost";

export const canvasV2ThemeSchema = z.enum(["light", "dark"]);
export type CanvasV2Theme = z.infer<typeof canvasV2ThemeSchema>;

export const canvasV2ViewportSchema = z.object({
  x: z.number(),
  y: z.number(),
  zoom: z.number().min(0.05).max(8),
});
export type CanvasV2Viewport = z.infer<typeof canvasV2ViewportSchema>;

export const CANVAS_V2_DATA_METHODS = [
  "query",
  "loadInsight",
  "capture",
  "run",
  "stateGet",
  "stateSet",
  "stateList",
  "stateEditText",
  "stateEditList",
  "actionInvoke",
  "agentRequest",
  "arrangeFragments",
] as const;
export type CanvasV2DataMethod = (typeof CANVAS_V2_DATA_METHODS)[number];

const channel = z.literal(CANVAS_V2_CHANNEL);

/** One other person's caret inside one mergeable field, as the frame draws it. */
export const canvasV2FrameCaretSchema = z.object({
  clientId: z.string().max(128),
  name: z.string().max(120),
  color: z.string().max(32),
  textColor: z.string().max(32),
  key: z.string().max(128),
  anchor: z.string().max(64).nullable(),
  focus: z.string().max(64).nullable(),
});
export type CanvasV2FrameCaret = z.infer<typeof canvasV2FrameCaretSchema>;

export const CANVAS_V2_MAX_FRAME_CARETS = 32;

export const hostToBoardFrameMessageSchema = z.discriminatedUnion("type", [
  z.object({
    channel,
    type: z.literal("init"),
    theme: canvasV2ThemeSchema,
    viewport: canvasV2ViewportSchema,
    fragments: z.array(canvasV2FragmentSchema),
    state: z.record(z.string(), z.unknown()),
  }),
  z.object({
    channel,
    type: z.literal("set-viewport"),
    viewport: canvasV2ViewportSchema,
  }),
  z.object({
    channel,
    type: z.literal("upsert-fragment"),
    fragment: canvasV2FragmentSchema.partial({ code: true }),
  }),
  z.object({ channel, type: z.literal("remove-fragment"), id: z.string() }),
  z.object({
    channel,
    type: z.literal("set-state"),
    key: z.string(),
    value: z.unknown(),
  }),
  z.object({
    channel,
    type: z.literal("set-theme"),
    theme: canvasV2ThemeSchema,
  }),
  z.object({
    channel,
    type: z.literal("set-selection"),
    ids: z.array(z.string()),
  }),
  z.object({
    channel,
    type: z.literal("set-focus"),
    id: z.string().nullable(),
  }),
  // True while a person drags or resizes on the board. A container fragment
  // holds its layout until the gesture ends, so it does not fight the pointer.
  z.object({ channel, type: z.literal("set-busy"), busy: z.boolean() }),
  z.object({
    channel,
    type: z.literal("set-carets"),
    carets: z.array(canvasV2FrameCaretSchema).max(CANVAS_V2_MAX_FRAME_CARETS),
  }),
  z.object({
    channel,
    type: z.literal("data-response"),
    id: z.string(),
    ok: z.boolean(),
    result: z.unknown().optional(),
    error: z.string().optional(),
  }),
]);
export type HostToBoardFrameMessage = z.infer<
  typeof hostToBoardFrameMessageSchema
>;

export const boardFrameToHostMessageSchema = z.discriminatedUnion("type", [
  z.object({ channel, type: z.literal("exit-focus") }),
  z.object({ channel, type: z.literal("ready") }),
  z.object({ channel, type: z.literal("fragment-rendered"), id: z.string() }),
  z.object({
    channel,
    type: z.literal("fragment-error"),
    id: z.string(),
    message: z.string().max(10_000),
    stack: z.string().max(50_000).optional(),
  }),
  z.object({
    channel,
    type: z.literal("state-changed"),
    key: z.string(),
    value: z.unknown(),
  }),
  z.object({
    channel,
    type: z.literal("data-request"),
    id: z.string().min(1).max(128),
    method: z.enum(CANVAS_V2_DATA_METHODS),
    payload: z.unknown(),
  }),
  z.object({
    channel,
    type: z.literal("wheel"),
    deltaX: z.number(),
    deltaY: z.number(),
    ctrlKey: z.boolean(),
    metaKey: z.boolean(),
    clientX: z.number(),
    clientY: z.number(),
  }),
  z.object({
    channel,
    type: z.literal("background-pointer"),
    phase: z.enum(["down", "move", "up"]),
    clientX: z.number(),
    clientY: z.number(),
    button: z.number(),
    shiftKey: z.boolean(),
    metaKey: z.boolean(),
    ctrlKey: z.boolean(),
    altKey: z.boolean(),
  }),
  z.object({
    channel,
    type: z.literal("pointer-move"),
    clientX: z.number(),
    clientY: z.number(),
  }),
  z.object({ channel, type: z.literal("pointer-leave") }),
  z.object({
    channel,
    type: z.literal("fragment-pointer-down"),
    id: z.string(),
    shiftKey: z.boolean(),
    metaKey: z.boolean(),
    ctrlKey: z.boolean(),
    altKey: z.boolean(),
  }),
  z.object({
    channel,
    type: z.literal("policy-violation"),
    directive: z.string().max(64),
    blocked: z.string().max(512),
  }),
  z.object({
    channel,
    type: z.literal("open-external"),
    url: z.string().url(),
  }),
]);
export type BoardFrameToHostMessage = z.infer<
  typeof boardFrameToHostMessageSchema
>;
