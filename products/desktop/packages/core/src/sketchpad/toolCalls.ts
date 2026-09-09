import {
  checkFragmentCode,
  findFreeSpot,
  maxZ,
  readMcpToolDescriptor,
  SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT,
  SKETCHPAD_FRAGMENT_DEFAULT_WIDTH,
  type SketchpadFragmentPatch,
  type SketchpadOp,
  type SketchpadSnapshot,
} from "@posthog/shared";
import { z } from "zod";

const LOCAL_TOOLS_SERVER = "posthog-code-tools";

export const SKETCHPAD_ADD_FRAGMENT_TOOL = "sketchpad_add_fragment";
export const SKETCHPAD_UPDATE_FRAGMENT_TOOL = "sketchpad_update_fragment";
export const SKETCHPAD_REMOVE_FRAGMENT_TOOL = "sketchpad_remove_fragment";
export const SKETCHPAD_SET_STATE_TOOL = "sketchpad_set_state";

const MUTATING_TOOLS: readonly string[] = [
  SKETCHPAD_ADD_FRAGMENT_TOOL,
  SKETCHPAD_UPDATE_FRAGMENT_TOOL,
  SKETCHPAD_REMOVE_FRAGMENT_TOOL,
  SKETCHPAD_SET_STATE_TOOL,
];

const READ_TOOLS: readonly string[] = [
  "sketchpad_list_fragments",
  "sketchpad_get_fragment",
  "sketchpad_get_state",
];

export function sketchpadToolName(meta: unknown): string | null {
  const descriptor = readMcpToolDescriptor(meta);
  if (!descriptor || descriptor.server !== LOCAL_TOOLS_SERVER) return null;
  const known =
    MUTATING_TOOLS.includes(descriptor.tool) ||
    READ_TOOLS.includes(descriptor.tool);
  return known ? descriptor.tool : null;
}

export function isSketchpadToolCall(meta: unknown): boolean {
  return sketchpadToolName(meta) !== null;
}

export function isSketchpadMutatingTool(name: string): boolean {
  return MUTATING_TOOLS.includes(name);
}

const geometryShape = {
  x: z.number().finite().optional(),
  y: z.number().finite().optional(),
  w: z.number().finite().min(80).max(4000).optional(),
  h: z.number().finite().min(60).max(4000).optional(),
};

const fragmentCodeSchema = z
  .string()
  .min(1)
  .max(200_000)
  .refine((code) => checkFragmentCode(code).ok, {
    message: "Fragment code may import only the pinned modules",
  });

const addFragmentInputSchema = z.object({
  id: z.string().min(1).max(64),
  code: fragmentCodeSchema,
  title: z.string().max(120).optional(),
  ...geometryShape,
});

const updateFragmentInputSchema = z.object({
  id: z.string().min(1).max(64),
  patch: z.object({
    code: fragmentCodeSchema.optional(),
    title: z.string().max(120).optional(),
    ...geometryShape,
  }),
});

const removeFragmentInputSchema = z.object({
  id: z.string().min(1).max(64),
});

const setStateInputSchema = z.object({
  key: z.string().min(1).max(128),
  value: z.unknown(),
});

export function toolCallToOp(
  tool: string,
  rawInput: unknown,
  snapshot: SketchpadSnapshot,
): SketchpadOp | null {
  switch (tool) {
    case SKETCHPAD_ADD_FRAGMENT_TOOL:
      return addFragmentOp(rawInput, snapshot);
    case SKETCHPAD_UPDATE_FRAGMENT_TOOL:
      return updateFragmentOp(rawInput);
    case SKETCHPAD_REMOVE_FRAGMENT_TOOL:
      return removeFragmentOp(rawInput);
    case SKETCHPAD_SET_STATE_TOOL:
      return setStateOp(rawInput);
    default:
      return null;
  }
}

export function normalizeFragmentId(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9-_]/g, "-")
    .replace(/^-+/, "")
    .slice(0, 64);
  return slug.length > 0 ? slug : "fragment";
}

function addFragmentOp(
  rawInput: unknown,
  snapshot: SketchpadSnapshot,
): SketchpadOp | null {
  const parsed = addFragmentInputSchema.safeParse(rawInput);
  if (!parsed.success) return null;
  const input = parsed.data;
  const w = input.w ?? SKETCHPAD_FRAGMENT_DEFAULT_WIDTH;
  const h = input.h ?? SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT;
  const spot =
    input.x === undefined || input.y === undefined
      ? findFreeSpot(snapshot, w, h)
      : { x: input.x, y: input.y };
  return {
    type: "add_fragment",
    fragment: {
      id: normalizeFragmentId(input.id),
      ...(input.title !== undefined && { title: input.title }),
      x: input.x ?? spot.x,
      y: input.y ?? spot.y,
      w,
      h,
      z: maxZ(snapshot) + 1,
      code: input.code,
      codeVersion: 1,
      surface: "card",
      hidden: false,
    },
  };
}

function updateFragmentOp(rawInput: unknown): SketchpadOp | null {
  const parsed = updateFragmentInputSchema.safeParse(rawInput);
  if (!parsed.success) return null;
  const { id, patch: raw } = parsed.data;
  const patch: SketchpadFragmentPatch = {};
  if (raw.code !== undefined) patch.code = raw.code;
  if (raw.title !== undefined) patch.title = raw.title;
  if (raw.x !== undefined) patch.x = raw.x;
  if (raw.y !== undefined) patch.y = raw.y;
  if (raw.w !== undefined) patch.w = raw.w;
  if (raw.h !== undefined) patch.h = raw.h;
  if (Object.keys(patch).length === 0) return null;
  return { type: "update_fragment", id: normalizeFragmentId(id), patch };
}

function removeFragmentOp(rawInput: unknown): SketchpadOp | null {
  const parsed = removeFragmentInputSchema.safeParse(rawInput);
  if (!parsed.success) return null;
  return { type: "remove_fragment", id: normalizeFragmentId(parsed.data.id) };
}

function setStateOp(rawInput: unknown): SketchpadOp | null {
  const parsed = setStateInputSchema.safeParse(rawInput);
  if (!parsed.success) return null;
  return {
    type: "set_state",
    key: parsed.data.key,
    value: parsed.data.value ?? null,
  };
}
