import { z } from "zod";

/**
 * Persisted browser-tab domain shapes for the Channels canvas surface.
 *
 * A tab stores references only (which canvas, which channel, which window,
 * and where in the strip). Display — label, icon, channel-hover — is resolved
 * at render time from the dashboard/channel records, never denormalised here.
 *
 * `scrollState` is reserved for a later follow-up (scroll restoration needs a
 * sandbox postMessage contract). It is persisted as opaque JSON so adding it
 * needs no migration.
 */
export const browserTabSchema = z.object({
  id: z.string(),
  windowId: z.string(),
  /** Canvas this tab shows. Null for a task tab or a blank tab. */
  dashboardId: z.string().nullable(),
  /** Task this tab shows. Null for a canvas tab or a blank tab. */
  taskId: z.string().nullable().default(null),
  channelId: z.string().nullable().default(null),
  /**
   * Channel sub-section this tab fronts (`artifacts` / `history` /
   * `context`). Null = the channel home, or a non-channel tab (canvas / task /
   * blank). Pairs with `channelId`: the two together identify a channel tab.
   */
  channelSection: z.string().nullable().default(null),
  /**
   * Top-level app page this tab shows (`inbox` / `agents` / `skills` /
   * `mcp-servers` / `command-center` / `home`). Null for a canvas / task /
   * channel / blank tab. These pages have no channel, task, or dashboard id, so
   * this is what lets them be a real tab target (label + restore-on-refocus).
   */
  appView: z.string().nullable().default(null),
  /** Gap-spaced ordering key within a window. Reindexed on collision. */
  position: z.number(),
  /**
   * Reserved/unwired. Opaque per-tab state for future scroll restoration etc.
   * Plain `z.unknown()` (not `.default(null)`) so the inferred shape matches
   * the tRPC-wire inference on the client — keeps the renderer facade type and
   * the transport type identical.
   */
  scrollState: z.unknown().optional(),
  createdAt: z.number(),
  lastActiveAt: z.number(),
});
export type BrowserTab = z.infer<typeof browserTabSchema>;

export const windowBoundsSchema = z.object({
  x: z.number(),
  y: z.number(),
  width: z.number(),
  height: z.number(),
});
export type WindowBounds = z.infer<typeof windowBoundsSchema>;

export const browserWindowSchema = z.object({
  id: z.string(),
  isPrimary: z.boolean(),
  /** Saved geometry for session restore. Null on web / before first persist. */
  bounds: windowBoundsSchema.nullable().default(null),
  /** Which tab is focused in this window. Null = channels landing. */
  activeTabId: z.string().nullable().default(null),
});
export type BrowserWindow = z.infer<typeof browserWindowSchema>;

/** Full persisted snapshot, the source of truth held by TabsService. */
export const tabsSnapshotSchema = z.object({
  windows: z.array(browserWindowSchema),
  tabs: z.array(browserTabSchema),
});
export type TabsSnapshot = z.infer<typeof tabsSnapshotSchema>;
