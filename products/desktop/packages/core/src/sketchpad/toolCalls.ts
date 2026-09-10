import {
  findFreeSpot,
  maxZ,
  normalizeFragmentId,
  readMcpToolDescriptor,
  SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
  SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT,
  SKETCHPAD_FRAGMENT_DEFAULT_WIDTH,
  SKETCHPAD_MUTATING_TOOL_NAMES,
  SKETCHPAD_READ_TOOL_NAMES,
  SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME,
  SKETCHPAD_SET_STATE_TOOL_NAME,
  SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME,
  type SketchpadFragmentPatch,
  type SketchpadOp,
  type SketchpadSnapshot,
  sketchpadAddFragmentShape,
  sketchpadRemoveFragmentShape,
  sketchpadSetStateShape,
  sketchpadUpdateFragmentShape,
} from "@posthog/shared";
import { z } from "zod";

const LOCAL_TOOLS_SERVER = "posthog-code-tools";

export function sketchpadToolName(meta: unknown): string | null {
  const descriptor = readMcpToolDescriptor(meta);
  if (!descriptor || descriptor.server !== LOCAL_TOOLS_SERVER) return null;
  const known =
    SKETCHPAD_MUTATING_TOOL_NAMES.includes(descriptor.tool) ||
    SKETCHPAD_READ_TOOL_NAMES.includes(descriptor.tool);
  return known ? descriptor.tool : null;
}

export function isSketchpadToolCall(meta: unknown): boolean {
  return sketchpadToolName(meta) !== null;
}

export function isSketchpadMutatingTool(name: string): boolean {
  return SKETCHPAD_MUTATING_TOOL_NAMES.includes(name);
}

export function toolCallToOp(
  tool: string,
  rawInput: unknown,
  snapshot: SketchpadSnapshot,
): SketchpadOp | null {
  switch (tool) {
    case SKETCHPAD_ADD_FRAGMENT_TOOL_NAME:
      return addFragmentOp(rawInput, snapshot);
    case SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME:
      return updateFragmentOp(rawInput);
    case SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME:
      return removeFragmentOp(rawInput);
    case SKETCHPAD_SET_STATE_TOOL_NAME:
      return setStateOp(rawInput);
    default:
      return null;
  }
}

function addFragmentOp(
  rawInput: unknown,
  snapshot: SketchpadSnapshot,
): SketchpadOp | null {
  const parsed = z.object(sketchpadAddFragmentShape).safeParse(rawInput);
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
  const parsed = z.object(sketchpadUpdateFragmentShape).safeParse(rawInput);
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
  const parsed = z.object(sketchpadRemoveFragmentShape).safeParse(rawInput);
  if (!parsed.success) return null;
  return { type: "remove_fragment", id: normalizeFragmentId(parsed.data.id) };
}

function setStateOp(rawInput: unknown): SketchpadOp | null {
  const parsed = z.object(sketchpadSetStateShape).safeParse(rawInput);
  if (!parsed.success) return null;
  return {
    type: "set_state",
    key: parsed.data.key,
    value: parsed.data.value ?? null,
  };
}
