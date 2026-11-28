# Performance

Read this before you change how tiles, panels or the grid render, what a context holds, or when a query runs.

Dashboards v2 aims for high performance and smooth frames on big dashboards, such as 200 tiles.
A change that is fine on a small dashboard can be slow or janky on a big one.
Judge each change at that size, not at the size of the fixture.
The sections between "Understand the cost" and "Measuring" go from the biggest effect on a big dashboard to the smallest.

## Understand the cost

- Cost is how often work runs, times how many elements it reaches, times what each element costs. A small cost repeated across hundreds of tiles on every pointer event blocks interaction.
- Tile count alone is a weak measure. Count rendered DOM nodes, chart points, observers and retained memory too. A few dense tables can cost more than many simple charts.
- A frame at 60 Hz lasts about 16.7 ms, shared with style, layout and paint. Scheduling work in an animation frame does not make it cheaper.
- Separate the phases before you optimize: initial load, the first movement of a gesture, continuous movement, release, and scroll and revisit. Each has different costs.

## Off-screen tiles

- A tile mounts its panel only once it scrolls into view (`grid/tileMounting.ts`). Do not add work that runs for every tile on load, such as a query, a measurement or a subscription, outside that gate.
- An unmounted tile keeps its place and shows a cheap placeholder, so a fast scroll never shows an empty cell.
- When many tiles come into view together, spread their mounts across frames, and cancel a pending mount when its tile leaves view first.
- A panel type's `keepMounted` keeps a panel mounted once it has been in view, for content that holds its own state. Each one stays in memory and keeps its subscriptions, so never set it on a chart.
- Work that a tile does when it mounts must also be correct when it mounts late, such as after a filter changed while it was off screen.

## Charts and queries

- Moving or resizing a tile reuses its chart instance and its query results. Only data changes run queries.
- When a canvas changes size, draw the new image in the same frame, so the chart never shows blank.
- Charts that mount together share one request through the query batch runner. Do not add a path that sends one request per tile.
- A change that runs queries again, such as a filter or a refresh, runs them for every mounted chart. Keep that set to the charts on screen, and make sure visible tiles do not wait behind off-screen ones.

## Re-renders

- Every consumer of a context re-renders when its value changes, and `memo` does not stop that. Before you add a field to a context, check how often it changes and how many components read it. `DashboardStateContext` changes on every edit, so a tile that reads it re-renders on every edit.
- Keep fast-changing state close to where it is used. Gesture geometry stays in the grid or the active tile, and filter drafts stay in the filter bar. Do not push them into a wide context on every pointer event or keystroke.
- Panels read only the small contexts they need (`FiltersContext`, `PanelHostContext`) and never the dashboard state. This keeps a dashboard edit from redrawing every chart.
- Keep a light wrapper for a tile's position separate from its expensive content, so moving a tile does not re-render what is inside it.
- Keep context values, props and callbacks stable between renders with `useMemo` and `useCallback`. A host that rebuilds its `DashboardController` on every render makes every consumer re-render every time.
- Keep tile keys and chart instances stable across moves, resizes and mode changes.
- Memoization saves React work only. It does not stop browser layout or canvas drawing when a size changes.
- When a context makes many components re-render for a change most of them ignore, split it, or put a stable store in it that components subscribe to by slice. Measure first.

## Layout and paint

- A class toggled on the grid restyles every tile it reaches, even when React skips their renders. End each rule under a gesture class on a narrow target, such as the placeholder or the dragged tile, and not on tile content. An inherited property set on tiles, such as `cursor` or `pointer-events`, has the same cost.
- Mount transient overlays, such as a drop hint, through a portal outside the grid, so inserting them does not restyle the tiles.
- Group geometry reads before DOM writes. Alternating them across tiles forces layout for each tile.
- Do not mount large control trees only because a gesture starts or ends.

## Work frequency

- Pointer events, resize observers and state updates can ask for the same work several times in one frame. Keep the latest state and combine the updates.
- Saving and other persistence stay out of the pointer event path. Save the finished layout.
- Throttling does not fix expensive work. A long callback still blocks every frame it runs in.
- Cancel scheduled work and listeners when a gesture ends or its target goes away.

## Code loading

- Load a panel type's or a kind of chart's component with `React.lazy`, so a page fetches only the kinds it draws. `PanelView` and `ChartPanel` already wrap them in `Suspense` with the type's loading state.
- Keep specs, schemas and the tile frame eager. Layout and validation need specs before any tile mounts, and the frame renders on every tile.
- Lazy-load at module level, once per component. A `lazy()` call inside a render makes a new component each time, which remounts the tile.
- Do not lazy-load a small component that every tile draws on first paint. A request per kind costs more than the bytes it saves.

## Measuring

- Check a change that touches any of the above on a big dashboard, not only on the kitchen sink fixture. Use invented data with dense tables and charts.
- Use the React profiler for re-renders and a browser trace for scripting, style, layout and paint. Fix the viewport, zoom and device pixel ratio, record a baseline, and change one thing at a time.
- Measure cold and warm separately: the first gesture after a fresh load, a repeat gesture, and a gesture after scrolling through every tile.
- Measure in a visible window. A hidden or covered window throttles animation frames, so its timings are not valid.
- Tests protect behavior. They do not show frame rate.
- In production, each load, refresh, filter change and tab switch sends a `dashboard v2 loaded` event, tagged with the host's `surface`. It carries the time to the first and last query result, query and cache counts, long main-thread tasks, and whether the page was hidden. A DevTools trace shows the same span as a `dashboard v2 <trigger>` measure.

[`products/dashboards/PERFORMANCE.md`](../../dashboards/PERFORMANCE.md) covers the v1 dashboard in more depth. Its code references and grid details do not apply to v2, but its measuring method does.
