import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import {
  checkFragmentCode,
  formatSketchpadForAgent,
  SKETCHPAD_ALLOWED_IMPORTS,
  SKETCHPAD_CONTENT_IS_DATA,
  SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT,
  SKETCHPAD_FRAGMENT_DEFAULT_WIDTH,
  sketchpadCacheFilePath,
  sketchpadCacheSchema,
} from "@posthog/shared";
import { z } from "zod";
import {
  defineLocalTool,
  type LocalToolCtx,
  type LocalToolGateMeta,
  type LocalToolResult,
} from "../registry";

export const SKETCHPAD_ADD_FRAGMENT_TOOL_NAME = "sketchpad_add_fragment";
export const SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME = "sketchpad_update_fragment";
export const SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME = "sketchpad_remove_fragment";
export const SKETCHPAD_SET_STATE_TOOL_NAME = "sketchpad_set_state";
export const SKETCHPAD_LIST_FRAGMENTS_TOOL_NAME = "sketchpad_list_fragments";
export const SKETCHPAD_GET_FRAGMENT_TOOL_NAME = "sketchpad_get_fragment";
export const SKETCHPAD_GET_STATE_TOOL_NAME = "sketchpad_get_state";

export const SKETCHPAD_TOOL_NAMES = [
  SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
  SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME,
  SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME,
  SKETCHPAD_SET_STATE_TOOL_NAME,
  SKETCHPAD_LIST_FRAGMENTS_TOOL_NAME,
  SKETCHPAD_GET_FRAGMENT_TOOL_NAME,
  SKETCHPAD_GET_STATE_TOOL_NAME,
] as const;

const WHITELISTED_PACKAGES = [...SKETCHPAD_ALLOWED_IMPORTS].filter(
  (name) => name !== "@posthog/canvas-sdk" && !name.startsWith("react/jsx"),
);

function fragmentCodeProblem(code: string | undefined): string | null {
  if (code === undefined) return null;
  const check = checkFragmentCode(code);
  if (check.ok) return null;
  return (
    "This code was not written to the board: " +
    check.violations.join("; ") +
    ". A fragment may import only: " +
    WHITELISTED_PACKAGES.join(", ") +
    ", and @posthog/canvas-sdk. It cannot load code any other way."
  );
}

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
  "fragment on the board shares, so fragments react to each other. " +
  "Use `SharedTextArea` for text a person types, `useSharedList` for a list " +
  "of items, and `useSharedState` for a setting. ";

const SIZE_RULES =
  "Units are CSS pixels at zoom 1. The origin is the top left corner. " +
  `The default size is ${SKETCHPAD_FRAGMENT_DEFAULT_WIDTH}×${SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT}. ` +
  "Keep fragments between 240×160 and 1200×800. Omit `x` and `y` to place the " +
  "fragment automatically in a free spot. ";

const COLLABORATION_RULES =
  "Other people edit this board at the same time. Call " +
  "`sketchpad_list_fragments` before you update or remove anything. Change only " +
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
      `Width in px at zoom 1. Default ${SKETCHPAD_FRAGMENT_DEFAULT_WIDTH}.`,
    ),
  h: z
    .number()
    .min(60)
    .max(4000)
    .optional()
    .describe(
      `Height in px at zoom 1. Default ${SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT}.`,
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
  return typeof meta?.sketchpadId === "string";
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
    return {
      ...cache,
      snapshot: {
        ...cache.snapshot,
        fragments: cache.snapshot.fragments.map(({ source, ...fragment }) => ({
          ...fragment,
          code: cache.sources[source],
        })),
      },
    };
  } catch {
    return null;
  }
}

export const canvasAddFragmentTool = defineLocalTool({
  name: SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
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
    const problem = fragmentCodeProblem(args.code);
    if (problem) return errorText(problem);
    return text(`Added fragment "${args.id}". Every collaborator sees it now.`);
  },
});

export const canvasUpdateFragmentTool = defineLocalTool({
  name: SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME,
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
    const problem = fragmentCodeProblem(args.patch.code);
    if (problem) return errorText(problem);
    const changed = Object.keys(args.patch);
    const summary = changed.length > 0 ? changed.join(", ") : "nothing";
    return text(
      `Updated fragment "${args.id}" (${summary}). Every collaborator sees the change now.`,
    );
  },
});

export const canvasRemoveFragmentTool = defineLocalTool({
  name: SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME,
  description: `Remove one fragment from the board for everyone. ${COLLABORATION_RULES}`,
  schema: canvasRemoveFragmentSchema,
  alwaysLoad: true,
  isEnabled,
  handler: async (_ctx, args): Promise<LocalToolResult> => {
    return text(`Removed fragment "${args.id}".`);
  },
});

export const canvasSetStateTool = defineLocalTool({
  name: SKETCHPAD_SET_STATE_TOOL_NAME,
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

export const canvasGetFragmentTool = defineLocalTool({
  name: SKETCHPAD_GET_FRAGMENT_TOOL_NAME,
  description:
    "Read one fragment in full, including its complete code, as JSON. Use it " +
    "before you change a fragment's code so you edit the current version.",
  schema: canvasGetFragmentSchema,
  alwaysLoad: true,
  isEnabled,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    const cache = await readSketchpadCache(ctx);
    if (!cache) return errorText(CACHE_UNAVAILABLE_TEXT);
    const fragment = cache.snapshot.fragments.find((f) => f.id === args.id);
    if (!fragment) {
      return errorText(
        `No fragment with id "${args.id}" on this board. Call sketchpad_list_fragments to see the current ids.`,
      );
    }
    return sketchpadContent(JSON.stringify(fragment, null, 2));
  },
});

export const canvasGetStateTool = defineLocalTool({
  name: SKETCHPAD_GET_STATE_TOOL_NAME,
  description:
    "Read the board's shared state as JSON. Pass `key` to read one value, or " +
    "omit it to read every key.",
  schema: canvasGetStateSchema,
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
  canvasAddFragmentTool,
  canvasUpdateFragmentTool,
  canvasRemoveFragmentTool,
  canvasSetStateTool,
  canvasListFragmentsTool,
  canvasGetFragmentTool,
  canvasGetStateTool,
];
