/**
 * Elevated z-index for the rebuilt taxonomic menu's portaled overlays — the
 * panel, its dropdown menu, the category select, and the DWH column select.
 *
 * These portal into `.main-content-container` (so the panel's `@container`
 * width query resolves), while an enclosing Lemon `Popover` the picker opens
 * from — a `More` / column-header menu — portals to the body-level floating
 * root. Both land on `--z-popover`, so on narrow viewports, where the panel
 * widens to overlap that menu, the tie breaks by DOM order and the enclosing
 * menu paints over the filter. One band above `--z-popover` lifts the filter
 * clear of it. The overlays share the value so their own order — the panel
 * below its child selects — is still decided by which opened last.
 */
export const NESTED_MENU_OVERLAY_Z_CLASS = 'z-[calc(var(--z-popover)+1)]'
