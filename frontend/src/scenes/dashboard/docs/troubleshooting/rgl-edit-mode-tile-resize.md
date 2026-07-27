# RGL edit-mode resize preview under tile content

In dashboard **edit mode**, dragging a tile resize handle shows the orange preview **under** the tile body instead of on top. View mode is unaffected — this is CSS/DOM glue in the dashboard scene fighting react-grid-layout, not stored layout JSON.

## How PostHog wires RGL

```text
ReactGridLayout (DashboardItems.tsx)
  └─ tile root = .react-grid-item  ← InsightCard / TextCard / ButtonTileCard / WidgetCard (same node)
       inline: position:absolute, transform, width, height  (RGL v2)
       children: tile content, DashboardResizeHandles (.handle), RGL .react-resizable-handle
```

Rules:

1. **Tile card root = RGL child** — one `div`, `forwardRef`. Scene wrappers must pass `ref`, `className`, `style`, and `children` (RGL resize handles) to that root unchanged.
2. **Decorative handles ≠ RGL handles** — `DashboardResizeHandles` (`.handle`) vs injected `.react-resizable-handle`. Both must be **direct children** of `.react-grid-item` (see `InsightCard`: handles outside `ErrorBoundary`).

## Cause

The white/orange resize preview is painted by RGL on `.react-resizable-handle`. PostHog also renders decorative `DashboardResizeHandles` (`.handle`) on the grid item. If `.handle` is not anchored to the full grid cell, its SVG overlays sit above the preview and look like content covering the resize ghost.

Common triggers:

- `.handle` missing `inset: 0` on `.react-grid-item > .handle`
- Handle markup placed on an inner wrapper instead of the tile root
- `DashboardResizeHandles` inside `ErrorBoundary` (viz errors can drop handles off the grid item)

## Files (check in this order)

1. `DashboardItems.scss` — `.react-grid-item > .handle`, placeholder z-index
2. `lib/components/Cards/handles.tsx` — decorative handle markup
3. Tile roots: `InsightCard.tsx`, `TextCard.tsx`, `ButtonTileCard.tsx`, product tile shells (e.g. `WidgetCard.tsx` + scene wrapper)
4. `DashboardItems.tsx` — tile render branches if a new wrapper broke `ref`/`style`/`children` forwarding

## Fix

### Decorative handles on the grid item

In `DashboardItems.scss`:

```scss
.react-grid-item > .handle {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
```

### Tile root prop order

```tsx
<div className={clsx('DashboardTileCard …', className)} {...divProps} style={style} ref={ref}>
  {/* content */}
  {showResizeHandles && <DashboardResizeHandles />}
  {children /* RGL .react-resizable-handle nodes */}
</div>
```

### Placeholder above grid background

```scss
.react-grid-item.react-grid-placeholder {
  position: relative;
  z-index: 2;
}
```

## Anti-patterns

| Do not                                                                          | Why                                                      |
| ------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `.react-grid-item.resizing { z-index: 105 }`                                    | Masks symptoms; breaks interaction                       |
| Handle CSS on inner wrappers without `inset: 0` on `.react-grid-item > .handle` | SVG overlays cover the orange preview                    |
| `DashboardResizeHandles` inside `ErrorBoundary`                                 | Handles must stay on the grid item root with RGL handles |

## Verify

1. Dashboard with mixed tile types (insight + text + button/widget if present).
2. Edit mode (E). Resize from the SE handle on each type.
3. Orange preview renders on top of tile content, aligned to the gray grid.
