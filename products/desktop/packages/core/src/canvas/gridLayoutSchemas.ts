import { z } from "zod";

// A grid canvas's layout document — its entire "source". Layout is data:
// publishes and patches are live immediately, with no build. The server
// validates authoritatively (geometry, overlaps, component references); these
// schemas are the transport shapes.

export const gridDefinitionSchema = z.object({
  columns: z.number().int(),
  rowHeight: z.number().int(),
  gap: z.number().int(),
});
export type GridDefinition = z.infer<typeof gridDefinitionSchema>;

export const placementStatusSchema = z.enum([
  "pending",
  "generating",
  "live",
  "failed",
]);
export type PlacementStatus = z.infer<typeof placementStatusSchema>;

export const gridPlacementSchema = z.object({
  id: z.string(),
  status: placementStatusSchema,
  // The component canvas this placement renders (required once live).
  component: z.string().nullish(),
  // "latest" (default) or a pinned source version id of the component.
  version: z.string().nullish(),
  x: z.number().int(),
  y: z.number().int(),
  w: z.number().int(),
  h: z.number().int(),
  // Per-placement settings, validated server-side against the component's
  // configSchema and delivered to the widget as ph.config.
  config: z.record(z.string(), z.unknown()).nullish(),
  // For pending/generating/failed placements: what the user asked the box to be.
  prompt: z.string().nullish(),
  // The agent task currently filling this placement, when one is running.
  generationTaskId: z.string().nullish(),
});
export type GridPlacement = z.infer<typeof gridPlacementSchema>;

const LATEST_COMPONENT_VERSION = "latest";

/** The component source version a placement pins, or null when it follows the
 * component's latest published build. */
export function pinnedComponentVersion(
  placement: Pick<GridPlacement, "version">,
): string | null {
  return placement.version && placement.version !== LATEST_COMPONENT_VERSION
    ? placement.version
    : null;
}

export const canvasLayoutSchema = z.object({
  schemaVersion: z.number(),
  grid: gridDefinitionSchema,
  placements: z.array(gridPlacementSchema),
});
export type CanvasLayout = z.infer<typeof canvasLayoutSchema>;

export const canvasLayoutResultSchema = z.object({
  layout: canvasLayoutSchema,
  // The head layout version — pass as expectedCurrentVersionId on writes.
  currentVersionId: z.string().nullish(),
});
export type CanvasLayoutResult = z.infer<typeof canvasLayoutResultSchema>;

// Fields an update op may merge into a placement (id is immutable).
export const placementChangesSchema = gridPlacementSchema
  .omit({ id: true })
  .partial();
export type PlacementChanges = z.infer<typeof placementChangesSchema>;

export const layoutOperationSchema = z.discriminatedUnion("op", [
  z.object({ op: z.literal("set_grid"), grid: gridDefinitionSchema }),
  z.object({ op: z.literal("add_placement"), placement: gridPlacementSchema }),
  z.object({
    op: z.literal("update_placement"),
    id: z.string(),
    changes: placementChangesSchema,
  }),
  z.object({ op: z.literal("remove_placement"), id: z.string() }),
]);
export type LayoutOperation = z.infer<typeof layoutOperationSchema>;

export const canvasLayoutInput = z.object({
  id: z.string().min(1),
  versionId: z.string().optional(),
});

export const publishLayoutInput = z.object({
  id: z.string().min(1),
  layout: canvasLayoutSchema,
  prompt: z.string().optional(),
  expectedCurrentVersionId: z.string().nullable(),
});

export const patchLayoutInput = z.object({
  id: z.string().min(1),
  operations: z.array(layoutOperationSchema).min(1),
  prompt: z.string().optional(),
  expectedCurrentVersionId: z.string().nullable(),
});

// A component's placement contract, snapshotted onto its head version and
// frozen into its build manifest.
export const componentSizeSchema = z.object({
  defaultW: z.number().int(),
  defaultH: z.number().int(),
  minW: z.number().int(),
  minH: z.number().int(),
  maxW: z.number().int().optional(),
  maxH: z.number().int().optional(),
});
export type ComponentSize = z.infer<typeof componentSizeSchema>;

export const componentMetaSchema = z.object({
  size: componentSizeSchema,
  configSchema: z.record(z.string(), z.unknown()).optional(),
});
export type ComponentMeta = z.infer<typeof componentMetaSchema>;
