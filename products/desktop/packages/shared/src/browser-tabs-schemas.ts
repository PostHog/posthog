import { z } from "zod";

/**
 * Persisted browser-tab domain shapes for the Channels canvas surface.
 *
 * A tab stores an `href` (the location it is on) plus the nav state that href
 * cannot express (`viewState`). The reference fields below — dashboard, task,
 * channel, section, appView — are a label/icon cache derived from the route,
 * never the source of truth for where a tab is. The resolved display name is
 * kept in viewState so a background tab can render immediately after restart,
 * before its record query has loaded.
 *
 * `scrollState` is reserved for a later follow-up (scroll restoration needs a
 * sandbox postMessage contract). It is persisted as opaque JSON so adding it
 * needs no migration.
 */
/**
 * A rail destination as a tab last left it. `href` alone cannot bring a visit
 * back: whether the space list was drawn over the space pane, and the space it
 * was drawn over, are view state rather than route.
 */
export const railVisitSchema = z.object({
  href: z.string(),
  listOpen: z.boolean().optional(),
  spaceId: z.string().nullable().optional(),
});
export type RailVisit = z.infer<typeof railVisitSchema>;

/**
 * The nav state a tab carries on top of its href: which sidebar pane is drawn,
 * which space is scoped when the route names none, and where each rail
 * destination was when this tab last left it.
 *
 * Scoped per tab because two tabs may sit on different spaces with different
 * sidebars; a window-global copy would let one tab's rail click restore an href
 * another tab established.
 */
export const tabViewStateSchema = z.object({
  /**
   * The last name this tab resolved for itself. A background tab's record is
   * not fetched, and the live lists that name it may not have loaded yet, so
   * without this a restored strip reads "Task" until they arrive. Written only
   * when a name actually resolves, so a loading frame cannot blank it.
   */
  title: z.string().optional(),
  listOpen: z.boolean().optional(),
  spaceId: z.string().nullable().optional(),
  /** Keyed by NavRailPane. Typed loosely here so shared stays route-agnostic. */
  lastByPane: z.record(z.string(), railVisitSchema).optional(),
});
export type TabViewState = z.infer<typeof tabViewStateSchema>;

export const browserTabSchema = z.object({
  id: z.string(),
  windowId: z.string(),
  /**
   * Where this tab is. The source of truth for restoring it: search params and
   * every route outside the reference vocabulary below survive only here.
   */
  href: z.string().nullable().default(null),
  /** Nav state the href cannot express. See {@link tabViewStateSchema}. */
  viewState: tabViewStateSchema.nullable().default(null),
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
   * Top-level app page this tab shows (for example `inbox`, `activity`, `loops`,
   * or `settings`). Null for a canvas / task / channel / blank tab. These pages
   * have no channel, task, or dashboard id, so this keeps their label metadata
   * alongside the canonical href.
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
