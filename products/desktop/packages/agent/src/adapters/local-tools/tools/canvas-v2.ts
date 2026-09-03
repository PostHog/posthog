import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import {
  CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT,
  CANVAS_V2_FRAGMENT_DEFAULT_WIDTH,
  type CanvasV2CachePayload,
  canvasV2CacheFilePath,
  canvasV2SnapshotSchema,
  formatBoardForAgent,
} from "@posthog/shared";
import { z } from "zod";
import {
  defineLocalTool,
  type LocalToolCtx,
  type LocalToolGateMeta,
  type LocalToolResult,
} from "../registry";

export const CANVAS_ADD_FRAGMENT_TOOL_NAME = "canvas_add_fragment";
export const CANVAS_UPDATE_FRAGMENT_TOOL_NAME = "canvas_update_fragment";
export const CANVAS_REMOVE_FRAGMENT_TOOL_NAME = "canvas_remove_fragment";
export const CANVAS_SET_STATE_TOOL_NAME = "canvas_set_state";
export const CANVAS_LIST_FRAGMENTS_TOOL_NAME = "canvas_list_fragments";
export const CANVAS_GET_FRAGMENT_TOOL_NAME = "canvas_get_fragment";
export const CANVAS_GET_STATE_TOOL_NAME = "canvas_get_state";

export const CANVAS_V2_TOOL_NAMES = [
  CANVAS_ADD_FRAGMENT_TOOL_NAME,
  CANVAS_UPDATE_FRAGMENT_TOOL_NAME,
  CANVAS_REMOVE_FRAGMENT_TOOL_NAME,
  CANVAS_SET_STATE_TOOL_NAME,
  CANVAS_LIST_FRAGMENTS_TOOL_NAME,
  CANVAS_GET_FRAGMENT_TOOL_NAME,
  CANVAS_GET_STATE_TOOL_NAME,
] as const;

const WHITELISTED_PACKAGES = [
  "react",
  "react-dom",
  "react-dom/client",
  "@posthog/quill",
  "recharts",
  "lucide-react",
  "dayjs",
  "d3",
  "three",
  "framer-motion",
  "zod",
  "@tanstack/react-table",
  "@tanstack/react-virtual",
  "react-hook-form",
  "lodash-es",
  "react-markdown",
  "papaparse",
];

const CACHE_UNAVAILABLE_TEXT =
  "The board cache is not available yet. Ask the person to open the board in the desktop app.";

const FRAGMENT_CONTRACT =
  "`code` is a complete TSX module. It must contain `export default function` " +
  "that returns a React component. It may import only from these packages: " +
  `${WHITELISTED_PACKAGES.join(", ")}, and \`@posthog/canvas-sdk\`. ` +
  'Use `import { ph, useSharedState } from "@posthog/canvas-sdk"` for data and ' +
  "shared state. `ph.query({ hogql })` or `ph.query({ query })` runs a PostHog " +
  "query. `ph.loadInsight({ shortId })` loads a saved insight. " +
  '`useSharedState("dateRange", initial)` reads and writes a value every ' +
  "fragment on the board shares, so fragments react to each other. ";

const SIZE_RULES =
  "Units are CSS pixels at zoom 1. The origin is the top left corner. " +
  `The default size is ${CANVAS_V2_FRAGMENT_DEFAULT_WIDTH}×${CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT}. ` +
  "Keep fragments between 240×160 and 1200×800. Omit `x` and `y` to place the " +
  "fragment automatically in a free spot. ";

const COLLABORATION_RULES =
  "Other people edit this board at the same time. Call " +
  "`canvas_list_fragments` before you update or remove anything. Change only " +
  "what you were asked to change. Do not remove fragments you did not create " +
  "unless the person asks. ";

const idField = z
  .string()
  .min(1)
  .max(64)
  .describe(
    "Short lowercase slug, unique on the board. Letters, digits, hyphens, " +
      'underscores. Examples: "date-range", "signups-kpi", "trend-chart".',
  );

const geometry = {
  x: z
    .number()
    .optional()
    .describe("Left edge in px at zoom 1. Omit to auto-place."),
  y: z
    .number()
    .optional()
    .describe("Top edge in px at zoom 1. Omit to auto-place."),
  w: z
    .number()
    .min(80)
    .max(4000)
    .optional()
    .describe(
      `Width in px at zoom 1. Default ${CANVAS_V2_FRAGMENT_DEFAULT_WIDTH}.`,
    ),
  h: z
    .number()
    .min(60)
    .max(4000)
    .optional()
    .describe(
      `Height in px at zoom 1. Default ${CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT}.`,
    ),
};

export const canvasAddFragmentSchema = {
  id: idField,
  code: z
    .string()
    .min(1)
    .max(200_000)
    .describe(
      "The full TSX module source. Must contain `export default function`.",
    ),
  title: z
    .string()
    .max(120)
    .optional()
    .describe("Short human title shown above the fragment."),
  ...geometry,
};

export const canvasUpdateFragmentSchema = {
  id: idField.describe("The id of an existing fragment on the board."),
  patch: z
    .object({
      code: z.string().min(1).max(200_000).optional(),
      title: z.string().max(120).optional(),
      ...geometry,
    })
    .describe(
      "Only the fields to change. Fields you omit keep their current value.",
    ),
};

export const canvasRemoveFragmentSchema = {
  id: idField.describe("The id of the fragment to remove."),
};

export const canvasSetStateSchema = {
  key: z
    .string()
    .min(1)
    .max(128)
    .describe(
      'The shared state key. Common keys: "dateRange" ({ date_from, date_to }), ' +
        '"filters", "selectedId".',
    ),
  value: z
    .unknown()
    .describe(
      "Any JSON value under 64 KB. Pass null to delete the key. Every " +
        "fragment that subscribes to this key updates at once.",
    ),
};

export const canvasGetFragmentSchema = {
  id: idField.describe("The id of the fragment to read."),
};

export const canvasGetStateSchema = {
  key: z
    .string()
    .max(128)
    .optional()
    .describe("One state key to read. Omit to read the whole state object."),
};

function isEnabled(
  _ctx: LocalToolCtx,
  meta: LocalToolGateMeta | undefined,
): boolean {
  return typeof meta?.canvasBoardId === "string";
}

function text(value: string): LocalToolResult {
  return { content: [{ type: "text", text: value }] };
}

function errorText(value: string): LocalToolResult {
  return { content: [{ type: "text", text: value }], isError: true };
}

async function readBoardCache(
  ctx: LocalToolCtx,
): Promise<CanvasV2CachePayload | null> {
  if (!ctx.canvasBoardId) return null;
  const filePath = canvasV2CacheFilePath(homedir(), ctx.canvasBoardId);
  let raw: string;
  try {
    raw = await readFile(filePath, "utf-8");
  } catch {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null) return null;
  const record = parsed as Record<string, unknown>;
  const snapshot = canvasV2SnapshotSchema.safeParse(record.snapshot);
  if (!snapshot.success) return null;
  return {
    boardId:
      typeof record.boardId === "string" ? record.boardId : ctx.canvasBoardId,
    name: typeof record.name === "string" ? record.name : "",
    headSeq: typeof record.headSeq === "number" ? record.headSeq : 0,
    snapshot: snapshot.data,
  };
}

/**
 * The mutating tools acknowledge only. The desktop renderer watches the
 * board session's completed tool calls and turns them into board ops, so the
 * agent process never needs a board API token.
 */
export const canvasAddFragmentTool = defineLocalTool({
  name: CANVAS_ADD_FRAGMENT_TOOL_NAME,
  description:
    "Add one fragment to the board. A fragment is a small live React app in a " +
    "rectangle on the board. One fragment per idea: one chart, one KPI, one " +
    "control. " +
    FRAGMENT_CONTRACT +
    SIZE_RULES +
    "If a fragment with the same id exists, it is replaced. " +
    COLLABORATION_RULES,
  schema: canvasAddFragmentSchema,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    return text(`Added fragment "${args.id}". Every collaborator sees it now.`);
  },
});

export const canvasUpdateFragmentTool = defineLocalTool({
  name: CANVAS_UPDATE_FRAGMENT_TOOL_NAME,
  description:
    "Change one existing fragment: its code, title, position, or size. Pass " +
    "only the fields to change. When you change `code`, pass the complete new " +
    "module, not a diff. " +
    FRAGMENT_CONTRACT +
    SIZE_RULES +
    COLLABORATION_RULES,
  schema: canvasUpdateFragmentSchema,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    const changed = Object.keys(args.patch);
    const summary = changed.length > 0 ? changed.join(", ") : "nothing";
    return text(
      `Updated fragment "${args.id}" (${summary}). Every collaborator sees the change now.`,
    );
  },
});

export const canvasRemoveFragmentTool = defineLocalTool({
  name: CANVAS_REMOVE_FRAGMENT_TOOL_NAME,
  description: `Remove one fragment from the board for everyone. ${COLLABORATION_RULES}`,
  schema: canvasRemoveFragmentSchema,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    return text(`Removed fragment "${args.id}".`);
  },
});

export const canvasSetStateTool = defineLocalTool({
  name: CANVAS_SET_STATE_TOOL_NAME,
  description:
    "Set one key of the board's shared state. All fragments on the board " +
    "share one state. A fragment that calls `useSharedState(key)` updates at " +
    'once. Convention: "dateRange" is `{ date_from, date_to }` (for example ' +
    '`{ "date_from": "-30d", "date_to": null }`), "filters" is an object, ' +
    '"selectedId" is a string. Pass null as the value to delete the key.',
  schema: canvasSetStateSchema,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    const verb = args.value === null ? "Deleted" : "Set";
    return text(`${verb} state key "${args.key}".`);
  },
});

export const canvasListFragmentsTool = defineLocalTool({
  name: CANVAS_LIST_FRAGMENTS_TOOL_NAME,
  description:
    "List every fragment on the board and the shared state keys. One line per " +
    "fragment: id · title · x,y · w×h · first code line. Call this before you " +
    "update or remove a fragment, and when the person asks what is on the board.",
  schema: {},
  alwaysLoad: true,
  isEnabled,
  handler: async (ctx): Promise<LocalToolResult> => {
    const cache = await readBoardCache(ctx);
    if (!cache) return errorText(CACHE_UNAVAILABLE_TEXT);
    const header = cache.name ? `Board: ${cache.name}\n` : "";
    return text(header + formatBoardForAgent(cache.snapshot, cache.headSeq));
  },
});

export const canvasGetFragmentTool = defineLocalTool({
  name: CANVAS_GET_FRAGMENT_TOOL_NAME,
  description:
    "Read one fragment in full, including its complete code, as JSON. Use it " +
    "before you change a fragment's code so you edit the current version.",
  schema: canvasGetFragmentSchema,
  alwaysLoad: true,
  isEnabled,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const cache = await readBoardCache(ctx);
    if (!cache) return errorText(CACHE_UNAVAILABLE_TEXT);
    const fragment = cache.snapshot.fragments.find((f) => f.id === args.id);
    if (!fragment) {
      return errorText(
        `No fragment with id "${args.id}" on this board. Call canvas_list_fragments to see the current ids.`,
      );
    }
    return text(JSON.stringify(fragment, null, 2));
  },
});

export const canvasGetStateTool = defineLocalTool({
  name: CANVAS_GET_STATE_TOOL_NAME,
  description:
    "Read the board's shared state as JSON. Pass `key` to read one value, or " +
    "omit it to read every key.",
  schema: canvasGetStateSchema,
  alwaysLoad: true,
  isEnabled,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const cache = await readBoardCache(ctx);
    if (!cache) return errorText(CACHE_UNAVAILABLE_TEXT);
    if (args.key === undefined) {
      return text(JSON.stringify(cache.snapshot.state, null, 2));
    }
    if (!(args.key in cache.snapshot.state)) {
      return text(`State key "${args.key}" is not set.`);
    }
    return text(JSON.stringify(cache.snapshot.state[args.key], null, 2));
  },
});

export const canvasV2Tools = [
  canvasAddFragmentTool,
  canvasUpdateFragmentTool,
  canvasRemoveFragmentTool,
  canvasSetStateTool,
  canvasListFragmentsTool,
  canvasGetFragmentTool,
  canvasGetStateTool,
];
