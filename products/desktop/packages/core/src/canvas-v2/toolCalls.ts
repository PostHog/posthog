import {
  CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT,
  CANVAS_V2_FRAGMENT_DEFAULT_WIDTH,
  type CanvasV2FragmentPatch,
  type CanvasV2Op,
  type CanvasV2Snapshot,
  findFreeSpot,
  maxZ,
  readMcpToolDescriptor,
} from "@posthog/shared";
import { z } from "zod";

// The local-tools MCP server that hosts the canvas tools. Mirrors the agent's
// LOCAL_TOOLS_MCP_NAME, hardcoded so core need not import @posthog/agent (same
// reason as showActions.ts). Matching the server as well as the tool keeps a
// third-party tool of the same name from writing to a board.
const LOCAL_TOOLS_SERVER = "posthog-code-tools";

export const CANVAS_V2_ADD_FRAGMENT_TOOL = "canvas_add_fragment";
export const CANVAS_V2_UPDATE_FRAGMENT_TOOL = "canvas_update_fragment";
export const CANVAS_V2_REMOVE_FRAGMENT_TOOL = "canvas_remove_fragment";
export const CANVAS_V2_SET_STATE_TOOL = "canvas_set_state";

const MUTATING_TOOLS: readonly string[] = [
  CANVAS_V2_ADD_FRAGMENT_TOOL,
  CANVAS_V2_UPDATE_FRAGMENT_TOOL,
  CANVAS_V2_REMOVE_FRAGMENT_TOOL,
  CANVAS_V2_SET_STATE_TOOL,
];

const READ_TOOLS: readonly string[] = [
  "canvas_list_fragments",
  "canvas_get_fragment",
  "canvas_get_state",
];

/** The tool name for a canvas-v2 tool call, or null for any other call. */
export function canvasV2ToolName(meta: unknown): string | null {
  const descriptor = readMcpToolDescriptor(meta);
  if (!descriptor || descriptor.server !== LOCAL_TOOLS_SERVER) return null;
  const known =
    MUTATING_TOOLS.includes(descriptor.tool) ||
    READ_TOOLS.includes(descriptor.tool);
  return known ? descriptor.tool : null;
}

export function isCanvasV2ToolCall(meta: unknown): boolean {
  return canvasV2ToolName(meta) !== null;
}

export function isCanvasV2MutatingTool(name: string): boolean {
  return MUTATING_TOOLS.includes(name);
}

const geometryShape = {
  x: z.number().finite().optional(),
  y: z.number().finite().optional(),
  w: z.number().finite().min(80).max(4000).optional(),
  h: z.number().finite().min(60).max(4000).optional(),
};

const addFragmentInputSchema = z.object({
  id: z.string().min(1).max(64),
  code: z.string().min(1).max(200_000),
  title: z.string().max(120).optional(),
  ...geometryShape,
});

const updateFragmentInputSchema = z.object({
  id: z.string().min(1).max(64),
  patch: z.object({
    code: z.string().min(1).max(200_000).optional(),
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

/**
 * The board ops one completed canvas tool call stands for. Invalid input yields
 * no ops, so a malformed call never writes to the shared log.
 */
export function toolCallToOps(
  tool: string,
  rawInput: unknown,
  snapshot: CanvasV2Snapshot,
): CanvasV2Op[] {
  switch (tool) {
    case CANVAS_V2_ADD_FRAGMENT_TOOL:
      return addFragmentOps(rawInput, snapshot);
    case CANVAS_V2_UPDATE_FRAGMENT_TOOL:
      return updateFragmentOps(rawInput);
    case CANVAS_V2_REMOVE_FRAGMENT_TOOL:
      return removeFragmentOps(rawInput);
    case CANVAS_V2_SET_STATE_TOOL:
      return setStateOps(rawInput);
    default:
      return [];
  }
}

/** Fragment ids are short lowercase slugs; weak models pass titles and camelCase. */
export function normalizeFragmentId(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9-_]/g, "-")
    .replace(/^-+/, "")
    .slice(0, 64);
  return slug.length > 0 ? slug : "fragment";
}

function addFragmentOps(
  rawInput: unknown,
  snapshot: CanvasV2Snapshot,
): CanvasV2Op[] {
  const parsed = addFragmentInputSchema.safeParse(rawInput);
  if (!parsed.success) return [];
  const input = parsed.data;
  const w = input.w ?? CANVAS_V2_FRAGMENT_DEFAULT_WIDTH;
  const h = input.h ?? CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT;
  const spot =
    input.x === undefined || input.y === undefined
      ? findFreeSpot(snapshot, w, h)
      : { x: input.x, y: input.y };
  return [
    {
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
      },
    },
  ];
}

function updateFragmentOps(rawInput: unknown): CanvasV2Op[] {
  const parsed = updateFragmentInputSchema.safeParse(rawInput);
  if (!parsed.success) return [];
  const { id, patch: raw } = parsed.data;
  const patch: CanvasV2FragmentPatch = {};
  if (raw.code !== undefined) patch.code = raw.code;
  if (raw.title !== undefined) patch.title = raw.title;
  if (raw.x !== undefined) patch.x = raw.x;
  if (raw.y !== undefined) patch.y = raw.y;
  if (raw.w !== undefined) patch.w = raw.w;
  if (raw.h !== undefined) patch.h = raw.h;
  if (Object.keys(patch).length === 0) return [];
  return [{ type: "update_fragment", id: normalizeFragmentId(id), patch }];
}

function removeFragmentOps(rawInput: unknown): CanvasV2Op[] {
  const parsed = removeFragmentInputSchema.safeParse(rawInput);
  if (!parsed.success) return [];
  return [{ type: "remove_fragment", id: normalizeFragmentId(parsed.data.id) }];
}

function setStateOps(rawInput: unknown): CanvasV2Op[] {
  const parsed = setStateInputSchema.safeParse(rawInput);
  if (!parsed.success) return [];
  return [
    {
      type: "set_state",
      key: parsed.data.key,
      value: parsed.data.value ?? null,
    },
  ];
}
