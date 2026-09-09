import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import {
  expandSketchpadCache,
  formatSketchpadForAgent,
  normalizeFragmentId,
  SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
  SKETCHPAD_CONTENT_IS_DATA,
  SKETCHPAD_GET_FRAGMENT_TOOL_NAME,
  SKETCHPAD_GET_STATE_TOOL_NAME,
  SKETCHPAD_LIST_FRAGMENTS_TOOL_NAME,
  SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME,
  SKETCHPAD_SET_STATE_TOOL_NAME,
  SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME,
  sketchpadAddFragmentShape,
  sketchpadCacheFilePath,
  sketchpadCacheSchema,
  sketchpadGetFragmentShape,
  sketchpadGetStateShape,
  sketchpadRemoveFragmentShape,
  sketchpadSetStateShape,
  sketchpadUpdateFragmentShape,
} from "@posthog/shared";
import { z } from "zod";
import { resolveSketchpadId } from "../../session-meta";
import {
  defineLocalTool,
  type LocalToolCtx,
  type LocalToolGateMeta,
  type LocalToolResult,
} from "../registry";

const CACHE_UNAVAILABLE_TEXT =
  "The board cache is not available yet. Ask the person to open the board in the desktop app.";

function isEnabled(
  _ctx: LocalToolCtx,
  meta: LocalToolGateMeta | undefined,
): boolean {
  return resolveSketchpadId(meta) !== undefined;
}

function text(value: string): LocalToolResult {
  return { content: [{ type: "text", text: value }] };
}

function sketchpadContent(value: string): LocalToolResult {
  return text(`${SKETCHPAD_CONTENT_IS_DATA}\n\n${value}`);
}

function errorText(value: string): LocalToolResult {
  return { content: [{ type: "text", text: value }], isError: true };
}

async function readSketchpadCache(ctx: LocalToolCtx) {
  if (!ctx.sketchpadId) return null;
  const filePath = sketchpadCacheFilePath(homedir(), ctx.sketchpadId);
  try {
    const cache = sketchpadCacheSchema.parse(
      JSON.parse(await readFile(filePath, "utf-8")),
    );
    return expandSketchpadCache(cache);
  } catch {
    return null;
  }
}

export const sketchpadAddFragmentTool = defineLocalTool({
  name: SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
  description:
    "Add one fragment to the board. Pass a complete TSX module and omit x/y to auto-place. Replaces a fragment with the same id.",
  schema: sketchpadAddFragmentShape,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    const parsed = z.object(sketchpadAddFragmentShape).safeParse(args);
    if (!parsed.success)
      return errorText(
        parsed.error.issues.map((issue) => issue.message).join("; "),
      );
    args = parsed.data;
    return text(
      `Queued fragment "${normalizeFragmentId(args.id)}" to be added.`,
    );
  },
});

export const sketchpadUpdateFragmentTool = defineLocalTool({
  name: SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME,
  description:
    "Change one fragment. Pass only the fields to change and the complete module when replacing code.",
  schema: sketchpadUpdateFragmentShape,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    const parsed = z.object(sketchpadUpdateFragmentShape).safeParse(args);
    if (!parsed.success)
      return errorText(
        parsed.error.issues.map((issue) => issue.message).join("; "),
      );
    args = parsed.data;
    const changed = Object.keys(args.patch);
    const summary = changed.join(", ");
    return text(
      `Queued changes to fragment "${normalizeFragmentId(args.id)}" (${summary}).`,
    );
  },
});

export const sketchpadRemoveFragmentTool = defineLocalTool({
  name: SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME,
  description: "Remove one fragment from the board for everyone.",
  schema: sketchpadRemoveFragmentShape,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    const parsed = z.object(sketchpadRemoveFragmentShape).safeParse(args);
    if (!parsed.success)
      return errorText(
        parsed.error.issues.map((issue) => issue.message).join("; "),
      );
    args = parsed.data;
    return text(
      `Queued fragment "${normalizeFragmentId(args.id)}" for removal.`,
    );
  },
});

export const sketchpadSetStateTool = defineLocalTool({
  name: SKETCHPAD_SET_STATE_TOOL_NAME,
  description: "Set one shared state key. Pass null to delete it.",
  schema: sketchpadSetStateShape,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    const parsed = z.object(sketchpadSetStateShape).safeParse(args);
    if (!parsed.success)
      return errorText(
        parsed.error.issues.map((issue) => issue.message).join("; "),
      );
    args = parsed.data;
    const verb = args.value === null ? "Deleted" : "Set";
    return text(
      `Queued shared state update: ${verb.toLowerCase()} key "${args.key}".`,
    );
  },
});

export const sketchpadListFragmentsTool = defineLocalTool({
  name: SKETCHPAD_LIST_FRAGMENTS_TOOL_NAME,
  description:
    "List every fragment on the board and the shared state keys. One line per " +
    "fragment: id · title · x,y · w×h · first code line. Call this before you " +
    "update or remove a fragment, and when the person asks what is on the board.",
  schema: {},
  alwaysLoad: true,
  isEnabled,
  handler: async (ctx): Promise<LocalToolResult> => {
    const cache = await readSketchpadCache(ctx);
    if (!cache) return errorText(CACHE_UNAVAILABLE_TEXT);
    const header = cache.name ? `Sketchpad: ${cache.name}\n` : "";
    return sketchpadContent(
      header + formatSketchpadForAgent(cache.snapshot, cache.headSeq),
    );
  },
});

export const sketchpadGetFragmentTool = defineLocalTool({
  name: SKETCHPAD_GET_FRAGMENT_TOOL_NAME,
  description:
    "Read one fragment in full, including its complete code, as JSON. Use it " +
    "before you change a fragment's code so you edit the current version.",
  schema: sketchpadGetFragmentShape,
  alwaysLoad: true,
  isEnabled,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const cache = await readSketchpadCache(ctx);
    if (!cache) return errorText(CACHE_UNAVAILABLE_TEXT);
    const fragment = cache.snapshot.fragments.find(
      (f) => f.id === normalizeFragmentId(args.id),
    );
    if (!fragment) {
      return errorText(
        `No fragment with id "${normalizeFragmentId(args.id)}" on this board. Call sketchpad_list_fragments to see the current ids.`,
      );
    }
    return sketchpadContent(JSON.stringify(fragment, null, 2));
  },
});

export const sketchpadGetStateTool = defineLocalTool({
  name: SKETCHPAD_GET_STATE_TOOL_NAME,
  description:
    "Read the board's shared state as JSON. Pass `key` to read one value, or " +
    "omit it to read every key.",
  schema: sketchpadGetStateShape,
  alwaysLoad: true,
  isEnabled,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const cache = await readSketchpadCache(ctx);
    if (!cache) return errorText(CACHE_UNAVAILABLE_TEXT);
    if (args.key === undefined) {
      return sketchpadContent(JSON.stringify(cache.snapshot.state, null, 2));
    }
    if (!(args.key in cache.snapshot.state)) {
      return text(`State key "${args.key}" is not set.`);
    }
    return sketchpadContent(
      JSON.stringify(cache.snapshot.state[args.key], null, 2),
    );
  },
});

export const sketchpadTools = [
  sketchpadAddFragmentTool,
  sketchpadUpdateFragmentTool,
  sketchpadRemoveFragmentTool,
  sketchpadSetStateTool,
  sketchpadListFragmentsTool,
  sketchpadGetFragmentTool,
  sketchpadGetStateTool,
];
