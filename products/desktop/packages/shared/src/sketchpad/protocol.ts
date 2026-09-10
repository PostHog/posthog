import { z } from "zod";
import { sketchpadFragmentSchema } from "./schemas";

export const SKETCHPAD_CHANNEL = "posthog-sketchpad";

export const sketchpadCompileRefsSchema = z
  .array(z.string().regex(/^[0-9a-f]{64}$/))
  .min(1)
  .max(256);
export const sketchpadCompiledFragmentSchema = z.object({
  code: z.string().max(4 * 1024 * 1024),
  imports: z.array(z.string()).max(32),
  error: z.string().max(10_000).nullable(),
});
export type SketchpadCompiledFragment = z.infer<
  typeof sketchpadCompiledFragmentSchema
>;
export const sketchpadCompiledResultsSchema = z.record(
  z.string(),
  sketchpadCompiledFragmentSchema,
);

export const SKETCHPAD_FRAME_NAME = "posthog-sketchpad";
export const SKETCHPAD_PARTITION = "sketchpad";
export const SKETCHPAD_URL = "posthog-sketchpad://sketchpad/";
export const SKETCHPAD_FRAME_TO_HOST_CHANNEL = "posthog-sketchpad-frame";
export const SKETCHPAD_HOST_TO_FRAME_CHANNEL = "posthog-sketchpad-host";
export const SKETCHPAD_FROM_HOST_FLAG = "__phFromHost";

export const sketchpadThemeSchema = z.enum(["light", "dark"]);
export type SketchpadTheme = z.infer<typeof sketchpadThemeSchema>;

export const sketchpadViewportSchema = z.object({
  x: z.number(),
  y: z.number(),
  zoom: z.number().min(0.05).max(8),
});
export type SketchpadViewport = z.infer<typeof sketchpadViewportSchema>;

export const SKETCHPAD_DATA_METHODS = [
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
export type SketchpadDataMethod = (typeof SKETCHPAD_DATA_METHODS)[number];

const channel = z.literal(SKETCHPAD_CHANNEL);

export const sketchpadFrameCaretSchema = z.object({
  clientId: z.string().max(128),
  name: z.string().max(120),
  color: z.string().max(32),
  textColor: z.string().max(32),
  key: z.string().max(128),
  anchor: z.string().max(64).nullable(),
  focus: z.string().max(64).nullable(),
});
export type SketchpadFrameCaret = z.infer<typeof sketchpadFrameCaretSchema>;

export const SKETCHPAD_MAX_FRAME_CARETS = 32;

export const hostToSketchpadFrameMessageSchema = z.discriminatedUnion("type", [
  z.object({
    channel,
    type: z.literal("init"),
    theme: sketchpadThemeSchema,
    viewport: sketchpadViewportSchema,
    fragments: z.array(sketchpadFragmentSchema),
    state: z.record(z.string(), z.unknown()),
  }),
  z.object({
    channel,
    type: z.literal("set-viewport"),
    viewport: sketchpadViewportSchema,
  }),
  z.object({
    channel,
    type: z.literal("upsert-fragment"),
    fragment: sketchpadFragmentSchema.partial({ code: true }),
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
    theme: sketchpadThemeSchema,
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
  z.object({ channel, type: z.literal("set-busy"), busy: z.boolean() }),
  z.object({
    channel,
    type: z.literal("set-carets"),
    carets: z.array(sketchpadFrameCaretSchema).max(SKETCHPAD_MAX_FRAME_CARETS),
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
export type HostToSketchpadFrameMessage = z.infer<
  typeof hostToSketchpadFrameMessageSchema
>;

export const sketchpadFrameToHostMessageSchema = z.discriminatedUnion("type", [
  z.object({
    channel,
    type: z.literal("compile-request"),
    id: z.string().max(64),
    refs: sketchpadCompileRefsSchema,
  }),
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
    method: z.enum(SKETCHPAD_DATA_METHODS),
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
export type SketchpadFrameToHostMessage = z.infer<
  typeof sketchpadFrameToHostMessageSchema
>;
