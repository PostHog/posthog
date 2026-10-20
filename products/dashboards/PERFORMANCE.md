# Dashboard performance

Use this guide for dashboard loading, edit mode, scrolling, tile movement, tile resize, and panel resize.
It applies to insight, text, image, button, and widget tiles.

## Understand the cost

Dashboard cost depends on how often work runs, how many tiles it reaches, and how expensive each tile is.
A small cost repeated across hundreds of tiles on every pointer event can block interaction.
A large cost paid once can delay the start even when subsequent frames are smooth.

Separate the phases before choosing an optimization:

| Phase                     | Costs to inspect                                                                 |
| ------------------------- | -------------------------------------------------------------------------------- |
| Initial load              | Requests, response processing, tile mounts, chart initialization, image decoding |
| Enter or exit edit mode   | State propagation, React renders, DOM changes, style and layout                  |
| First movement            | Input handlers, grid activation, synchronous work before the first paint         |
| Continuous move or resize | Grid calculations, affected tile renders, layout, chart drawing, paint           |
| Release and save          | Final geometry, chart redraw, serialization, request time, response processing   |
| Scroll and revisit        | Mounts, retained resources, observer callbacks, repeated queries                 |

At 60 Hz, a frame lasts about 16.7 ms. JavaScript shares this time with browser rendering and other work.
An animation frame callback schedules work before a paint; it does not make that work cheaper.
A save request can overlap UI work. Use the browser timeline to separate server wait from work that blocks the interface.

## Findings from a dense local dashboard

We compared one change group at a time on a local dashboard with 89 mixed tiles.
The browser viewport was 1504 by 1575 pixels at a device pixel ratio of 2, with no CPU throttle.
Each run entered and exited edit mode six times, scrolled through the dashboard, then repeated the mode change three times.
The table uses the median of those final three changes. The current implementation ranged from 156 to 179 ms to enter and 139 to 166 ms to exit across reference runs.

| Change removed for one run                  | Edit entry | Edit exit | Finding                                                                                                                         |
| ------------------------------------------- | ---------: | --------: | ------------------------------------------------------------------------------------------------------------------------------- |
| Local edit-mode state change                |     311 ms |    273 ms | State changes through the async dashboard loader caused the largest transition cost.                                            |
| Stable tile callbacks and decorations       |     280 ms |    242 ms | New references spread a mode change into card renders.                                                                          |
| SVG grid background                         |     278 ms |    162 ms | Thousands of grid-cell elements mainly delayed entry.                                                                           |
| Skip save work when the layout is unchanged |     230 ms |    286 ms | Local save work delayed exit even when neither version sent a dashboard PATCH request.                                          |
| Mount insight cards near the viewport       |     240 ms |    225 ms | Mounted insight cards rose from 2 to 49 without this limit. This run used an earlier version that unmounted cards after scroll. |

These results measure each group's contribution to the current branch. They are not additive or a comparison against `master`.
Fresh-load timing varied, so small differences need more evidence. At normal CPU speed, drag and resize had a median frame interval near 16.7 ms with every measured variant. The changes above mainly improved mode transitions and retained work; they did not establish a continuous-frame-rate gain.

A separate browser run compared the dashboard code before this PR with the current code, while both used the installed grid library version 2.3.0. The local dashboard had 89 mixed tiles. The viewport was 1504 by 1519 pixels at device pixel ratio 2, with no CPU throttle. Each variant ran three 60-frame corner resizes and three 60-frame drags.

| Interaction   | Before: median / p95 frame interval | Current: median / p95 frame interval | Frames over 25 ms                  |
| ------------- | ----------------------------------- | ------------------------------------ | ---------------------------------- |
| Corner resize | 16.7 / 33.3–33.7 ms                 | 16.7 / 17.4–17.6 ms                  | 10 of 177 before; 0 of 177 current |
| Drag          | 16.7 / 17.5–17.6 ms                 | 16.7 / 17.4–17.6 ms                  | 0 of 177 in both                   |

The resize comparison shows fewer slow frames in this synthetic local gesture. It does not measure the grid library upgrade, slower devices, or production dashboards. Median FPS stayed near 60 in both variants, so the result is a reduction in resize frame spikes, not a median FPS increase.

Removing content visibility, closed screenshot-editor deferral, the insight-card memo boundary alone, or persistent edge controls produced small or inconsistent timing differences in this setup.
Do not rank those as proven gains without another workload that exposes their cost.
A layout-compactor change reduced one 89-item helper call from about 0.009 to 0.002 ms in isolation. That difference alone cannot explain a visible delay.
An isolated line-chart scale cache reduced calculation time but did not improve frame intervals, so we removed it.
The grid-library upgrade, pointer handoff, and live chart redraw also affect correctness or visible behavior. This comparison did not isolate their performance effect.

## Limit how far state changes spread

React work grows with the number of components affected by a change.
Dashboard-wide state can make every card render even when only one tile moves.

- Keep transient geometry close to the grid or active tile.
- Separate a light geometry wrapper from expensive card content.
- Preserve references for unchanged data, configuration, layout items, and callbacks where render boundaries depend on them.
- Check which props actually change before adding memoization.
- Keep comparisons correct. Ignoring changed callbacks or content can preserve stale behavior.
- Preserve tile keys and chart instances across geometry and mode changes.
- Keep local edit-mode state changes out of dashboard data loaders when no dashboard data changed.

Memoization reduces repeated React work. It does not prevent browser layout or canvas drawing after dimensions change.
For example, moving a tile usually needs a position update; resizing it can also require text layout and a chart redraw.

## Control work frequency

Pointer events, resize observers, state updates, and chart schedulers can request the same work more than once per frame.
Keep the latest required state and combine redundant updates at the appropriate boundary.

- Update visible pixel geometry at the cadence needed to follow the pointer.
- Run collision and compaction calculations when their grid inputs change.
- Combine chart draw requests through the existing frame scheduler.
- Keep persistence out of the pointer event path. Save the completed layout.
- Cancel scheduled work and listeners when the interaction ends or its target disappears.

Do not assume throttling fixes expensive work. A long callback can still block every frame in which it runs.
Check first movement, final movement, quick release, and cancellation when changing scheduling.
Deferred activation must retain the latest pointer position and wait until the grid can accept it.

## Bound browser layout and paint

DOM size, CSS dependencies, and visible area affect style calculation, layout, paint, and compositing.
A global class change can invalidate many tiles even when React skips their renders.

- Inspect browser style and layout costs alongside React commits.
- Avoid alternating geometry reads and DOM writes across tiles. Group required reads before writes.
- Avoid mounting large control trees solely because edit mode changes.
- Defer hidden controls that perform measurements or other expensive initialization.
- Use containment or content visibility where appropriate, and check overflow, overlays, focus, and active gestures.
- Keep decorative DOM bounded. Repeated backgrounds need not create an element for every grid cell.
- Count DOM nodes before and after mode changes. CSS containment cannot remove the cost of creating thousands of nodes.

Transforms can reduce layout work for position changes. Width and height changes can require layout through the tile's content.
Containment does not remove React work, query work, timers, or canvas resources by itself.
In a vertically compacted grid, shrinking a tile from its top edge opens space above it. Compaction can pull lower tiles upward during that gesture. Keep the top edge fixed when that movement is unwanted.

## Bound mounted content and retained resources

A long dashboard should avoid mounting every expensive card at initial load.
Track DOM nodes, chart instances, observers, timers, decoded images, and memory after a full scroll and return.

- Mount expensive content near the viewport when the surface permits it.
- Apply that limit to widget bodies as well as insight charts. Offscreen list widgets can retain thousands of DOM nodes.
- Keep live widget bodies mounted because their data streams update in the component.
- Keep a card mounted after its first display if it owns saves, query results, refresh polling, or mutation recovery.
- Release offscreen resources only after their work and state have a durable owner elsewhere.
- Preserve active gestures, open dialogs or details, and export rendering.
- Keep enough layout information to preserve tile positions while content is absent.
- Render a cheap placeholder for an unmounted tile so a fast scroll never exposes an empty grid cell.
- Avoid a second visibility delay after the tile mounts; the mount boundary already limits offscreen work.
- Avoid remounting neighboring content solely because its position changes.
- Inspect existing observer sharing before introducing another observer layer.

Choose the viewport margin from the tradeoff between preparation time and retained work.
A mount-once policy delays initial cost but can still retain the entire dashboard after scrolling.
Unmounting can also cause repeated initialization or queries; measure both resource use and revisit behavior.

## Make chart resize proportional to the change

Chart cost depends on visible chart count, series count, point count, labels, axes, and canvas pixel area.
Higher device pixel ratios increase backing-store area. A larger canvas can cost more even with unchanged data.

- Reuse chart instances and query results when only dimensions change.
- Separate data preparation from size-dependent ranges and drawing.
- Cache expensive calculations only when all invalidation inputs are understood.
- Include data, axis configuration, stacking, scale type, and size-dependent tick choices where they affect a cached result.
- Profile point processing, text measurement, axes, and drawing separately before choosing a cache or data reduction.
- Preserve hidden-page limits and context-loss recovery.

Keep the chart visible while replacing its image.
Changing a canvas width or height clears its bitmap; update the backing store and draw the replacement in the same scheduled operation.
A frozen or stretched chart changes the experience. Treat that as a product tradeoff when live redraw is required.

## Separate data work from geometry

Moving or resizing a tile should reuse its current data unless dimensions are an explicit query input.
Mode changes and virtualization must not accidentally invalidate queries or start duplicate requests.

- Distinguish data loading state from local interaction state.
- Inspect request counts during mode changes, gestures, scrolling, and revisits.
- Bound query concurrency and response processing during dashboard load or refresh.
- Avoid unnecessary saves when no persisted state changed.
- Preserve save errors, cancellation, and final layout correctness when moving work off the interaction path.
- Check the local work done by an unchanged save. Zero network requests do not prove that exit is cheap.

A fast network response can still cause a slow interface if parsing, state propagation, or rendering is expensive.
A slow request does not explain a delayed local drag unless the interaction actually waits for it.

## Measure the affected experience

Respect the user's constraints on runtime checks, tests, and publishing.
If checks are paused, identify the unverified behavior and leave the change local.

1. Define the phase and observable result: input-to-paint latency, frame intervals, long tasks, request count, or retained resources.
2. Use invented data with representative tile types, chart complexity, dashboard length, and layout density.
3. Record a baseline with fixed viewport, zoom, device pixel ratio, browser, and CPU settings.
4. Use a browser trace to locate scripting, React, style, layout, paint, and network costs.
5. Change one suspected cause. Repeat the same interaction and report variation.
6. Stop traces and detach diagnostic sessions. Repeat timing measurements without profiling overhead.

An A/B comparison needs a stable outcome as well as a timing difference.
Check that both variants save, cancel, move, resize, and display charts correctly.
If a change improves only a helper benchmark while the browser frame intervals remain unchanged, report the helper result without claiming smoother interaction.

Check the following boundaries for interaction changes:

- Entry, first movement, continuous movement, release, exit, and saved-layout reload.
- One movement followed by a pause, movement below the drag threshold, quick release, and cancellation.
- Horizontal and vertical resize, affected neighbors, and supported compaction modes.
- A narrow scene with an open side panel, plus a wide scene.
- A full scroll and return, including mounted content, memory, and request counts.
- Chart line visibility throughout resize. A screenshot at rest cannot establish the absence of blank frames.

Report the conditions, user-visible result, and remaining gaps.
Focused regression tests can protect behavior; they do not establish frame rate.
Do not convert one local result into a general performance guarantee.

## Code references

- [Dashboard grid and event handlers](../../frontend/src/scenes/dashboard/DashboardItems.tsx).
- [Interaction state and layout commits](../../frontend/src/scenes/dashboard/useDashboardLayoutInteraction.ts).
- [Neighbor resize](../../frontend/src/scenes/dashboard/dashboardResizeCompactor.ts) and [compaction modes](./frontend/dashboardCustomization.ts).
- [Insight card lifecycle](../../frontend/src/lib/components/Cards/InsightCard/InsightCard.tsx).
- [Canvas sizing](../../packages/quill/packages/charts/src/core/hooks/useChartCanvas.ts) and [draw scheduling](../../packages/quill/packages/charts/src/core/hooks/useChartDraw.ts).
- [Dashboard engineering skill](../../.agents/skills/managing-dashboards/SKILL.md) for access, queries, and surface contracts.

Read other dashboard implementations to form hypotheses about architecture and scheduling.
Check their library versions and workload before transferring an approach. Measure the result in PostHog.
