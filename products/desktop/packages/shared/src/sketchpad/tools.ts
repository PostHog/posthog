import { z } from "zod";
import {
  checkFragmentCode,
  SKETCHPAD_ALLOWED_IMPORTS,
} from "./fragmentCodeGuard";
import { estimateJsonBytes } from "./ops";
import {
  SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT,
  SKETCHPAD_FRAGMENT_DEFAULT_WIDTH,
  SKETCHPAD_MAX_STATE_VALUE_BYTES,
} from "./schemas";

const fragmentCodeSchema = z
  .string()
  .min(1)
  .max(200_000)
  .refine((code) => checkFragmentCode(code).ok, {
    message: `Fragment code may import only the pinned modules: ${[...SKETCHPAD_ALLOWED_IMPORTS].join(", ")}.`,
  });

export const SKETCHPAD_ADD_FRAGMENT_TOOL_NAME = "sketchpad_add_fragment";
export const SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME = "sketchpad_update_fragment";
export const SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME = "sketchpad_remove_fragment";
export const SKETCHPAD_SET_STATE_TOOL_NAME = "sketchpad_set_state";
export const SKETCHPAD_LIST_FRAGMENTS_TOOL_NAME = "sketchpad_list_fragments";
export const SKETCHPAD_GET_FRAGMENT_TOOL_NAME = "sketchpad_get_fragment";
export const SKETCHPAD_GET_STATE_TOOL_NAME = "sketchpad_get_state";

export const SKETCHPAD_MUTATING_TOOL_NAMES: readonly string[] = [
  SKETCHPAD_ADD_FRAGMENT_TOOL_NAME,
  SKETCHPAD_UPDATE_FRAGMENT_TOOL_NAME,
  SKETCHPAD_REMOVE_FRAGMENT_TOOL_NAME,
  SKETCHPAD_SET_STATE_TOOL_NAME,
];
export const SKETCHPAD_READ_TOOL_NAMES: readonly string[] = [
  SKETCHPAD_LIST_FRAGMENTS_TOOL_NAME,
  SKETCHPAD_GET_FRAGMENT_TOOL_NAME,
  SKETCHPAD_GET_STATE_TOOL_NAME,
];

const idField = z
  .string()
  .min(1)
  .max(64)
  .describe(
    "Short lowercase slug, unique on the board. Letters, digits, hyphens, " +
      'underscores. Examples: "date-range", "signups-kpi", "trend-chart".',
  );

export const sketchpadGeometryShape = {
  x: z
    .number()
    .finite()
    .optional()
    .describe("Left edge in px at zoom 1. Omit to auto-place."),
  y: z
    .number()
    .finite()
    .optional()
    .describe("Top edge in px at zoom 1. Omit to auto-place."),
  w: z
    .number()
    .finite()
    .min(80)
    .max(4000)
    .optional()
    .describe(
      `Width in px at zoom 1. Default ${SKETCHPAD_FRAGMENT_DEFAULT_WIDTH}.`,
    ),
  h: z
    .number()
    .finite()
    .min(60)
    .max(4000)
    .optional()
    .describe(
      `Height in px at zoom 1. Default ${SKETCHPAD_FRAGMENT_DEFAULT_HEIGHT}.`,
    ),
};

export const sketchpadAddFragmentShape = {
  id: idField,
  code: fragmentCodeSchema.describe(
    "The full TSX module source. Must contain export default function.",
  ),
  title: z
    .string()
    .max(120)
    .optional()
    .describe("Short human title shown above the fragment."),
  ...sketchpadGeometryShape,
};

export const sketchpadUpdateFragmentShape = {
  id: idField.describe("The id of an existing fragment on the board."),
  patch: z
    .object({
      code: fragmentCodeSchema.optional(),
      title: z.string().max(120).optional(),
      ...sketchpadGeometryShape,
    })
    .refine(
      (patch) => Object.values(patch).some((value) => value !== undefined),
      { message: "Pass at least one field to update." },
    )
    .describe(
      "Only the fields to change. Fields you omit keep their current value.",
    ),
};

export const sketchpadRemoveFragmentShape = {
  id: idField.describe("The id of the fragment to remove."),
};

export const sketchpadSetStateShape = {
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
    .refine(
      (value) => estimateJsonBytes(value) <= SKETCHPAD_MAX_STATE_VALUE_BYTES,
      { message: "The shared state value is too large." },
    )
    .describe(
      "Any JSON value under 64 KB. Pass null to delete the key. Every " +
        "fragment that subscribes to this key updates at once.",
    ),
};

export const sketchpadGetFragmentShape = {
  id: idField.describe("The id of the fragment to read."),
};

export const sketchpadGetStateShape = {
  key: z
    .string()
    .min(1)
    .max(128)
    .optional()
    .describe("One state key to read. Omit to read the whole state object."),
};

export function normalizeFragmentId(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9-_]/g, "-")
    .replace(/^-+/, "")
    .slice(0, 64);
  return slug.length > 0 ? slug : "fragment";
}
