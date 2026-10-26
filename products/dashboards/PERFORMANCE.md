# Dashboard performance

Use this guide for dashboard loading, edit mode, scrolling, tile movement, tile resize, and panel resize.
It applies to insight, text, image, button, and widget tiles.

## Understand the cost

Dashboard cost depends on how often work runs, how many elements it reaches, and how expensive each element is.
A small cost repeated across hundreds of tiles on every pointer event can block interaction.
A large cost paid once can delay the start even when subsequent frames are smooth.
Tile count alone is a weak measure. Include rendered cells, chart points, DOM nodes, observers, and retained memory.

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

## Identify the limiting resource

The browser main thread runs input handlers, JavaScript, React commits, style calculation, layout, and paint.
Any one of these can delay the next frame. A slow network request can delay content without blocking input.
The two delays need different fixes.

- **CPU:** Repeated selectors, renders, data transforms, and chart drawing compete for frame time.
- **DOM and style:** Many nodes and broad CSS changes increase style and layout work, including for content outside view.
- **Memory:** Mounted tables, chart buffers, images, and observers remain after a scroll unless their lifecycle releases them.
- **Network and server:** Query execution, bounded concurrency, and cache state determine when data becomes available.
- **Scheduling:** Work that is cheap alone can cause a stall when many tiles start it in the same frame.

Measure cold and warm states separately. A fresh load can mount tiles, build caches, and initialize grid controls during the first interaction.
A repeat gesture on the same page omits those costs. A full scroll can leave more content mounted than either state.
Compare those states with the same viewport, data, and input gesture.

Optimize the user-visible result, not only one resource. Deferring mounts can shorten a frame stall but extend placeholder time.
Virtualizing rows can reduce DOM size but change column sizing. Reducing query concurrency can protect the server but delay visible tiles.

## Limit how far state changes spread

React work grows with the number of components affected by a change.
Dashboard-wide state can make every card render even when only one tile moves.

- Keep transient geometry close to the grid or active tile.
- Keep completed layout edits separate from dashboard tile data until Save. Replacing every tile on pointer release can invalidate dashboard-wide selectors and delay the next paint.
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
Check third-party drag and resize code for global style changes. Recheck upstream behavior before changing a local workaround.

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
Measure edit entry after a full scroll. Dense SQL tables can make this transition slow even when the tile count is unchanged.
Count rendered cells and DOM nodes as well as tiles. A few dense tables can cost more than many simple charts.

- Mount expensive content near the viewport when the surface permits it.
- Apply that limit to widget bodies as well as insight charts. Offscreen list widgets can retain thousands of DOM nodes.
- Before unmounting a live widget, preserve its data stream and recovery state outside the component.
- Keep a card mounted after its first display if it owns saves, query results, refresh polling, or mutation recovery.
- Release offscreen resources only after their work and state have a durable owner elsewhere.
- Preserve active gestures, open dialogs or details, and export rendering.
- Keep enough layout information to preserve tile positions while content is absent.
- Render a cheap placeholder for an unmounted tile so a fast scroll never exposes an empty grid cell.
- When many tiles enter view together, spread expensive mounts across frames and show a useful placeholder.
- Cancel a pending mount if its tile leaves view before the mount starts.
- Avoid remounting neighboring content solely because its position changes.
- Inspect existing observer sharing before introducing another observer layer.

Choose the viewport margin from the tradeoff between preparation time and retained work.
A mount-once policy delays initial cost but can still retain the entire dashboard after scrolling.
Unmounting can also cause repeated initialization or queries; measure both resource use and revisit behavior.
For a fast scroll jump, measure the longest frame and the time until every newly visible card displays content.
Spreading mounts across frames can reduce one stall while increasing the time a visible card shows a placeholder.
For virtualized tables, check column widths, pinned columns, horizontal scroll, the last row, and export.

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
- Trace tile delivery, card mount, query queue wait, query execution, and result paint separately during a cold load.
- Check whether visible tiles wait behind offscreen tiles in a bounded refresh queue.
- Avoid unnecessary saves when no persisted state changed.
- Preserve save errors, cancellation, and final layout correctness when moving work off the interaction path.
- Check the local work done by an unchanged save. Zero network requests do not prove that exit is cheap.

A fast network response can still cause a slow interface if parsing, state propagation, or rendering is expensive.
A slow request does not explain a delayed local drag unless the interaction actually waits for it.

SQL result tables in dashboard cards use row virtualization inside the tile's scroll area.
Tables with more than 50 columns also use column virtualization with fixed column widths, unless pinned columns require the full column layout.
Image exports keep the full table layout.
Table renderers prepare cells by row and column index, including transposed cells, so offscreen cells do not require formatting before display.
Sorting prepares the selected column once per column configuration; comparisons reuse those cells.
Tables skip chart aggregation. Virtualization does not reduce query result size or response parsing.

## Measure the affected experience

Respect the user's constraints on runtime checks, tests, and publishing.
If checks are paused, identify the unverified behavior and leave the change local.

1. Define the phase and observable result: input-to-paint latency, frame intervals, long tasks, request count, or retained resources.
2. Use invented data with representative tile types, chart complexity, dashboard length, and layout density.
   Include dense SQL tables and tiles with different row and column counts.
3. Record a baseline with fixed viewport, zoom, device pixel ratio, browser, and CPU settings.
4. Use a browser trace to locate scripting, React, style, layout, paint, and network costs.
5. Change one suspected cause. Repeat the same interaction and report variation.
6. Measure pointer release separately from continuous movement. Include the synchronous work before mouse-up returns and the next paint.
7. For a long dashboard, scroll through every tile before the gesture. Retained tables and charts can change the release cost.
8. If release is slow, trace the final grid callback through Kea actions, reducers, selectors, React commits, and browser work. A fast grid calculation does not prove a fast commit.
9. Compare against a temporary no-op for the suspected update, then restore it. Confirm that the measured cost belongs to that update before changing state ownership.
10. Stop traces and detach diagnostic sessions. Repeat timing measurements without profiling overhead.
11. Compare the first gesture after a fresh load with a repeat gesture on the same page. Record whether tiles still mount during the gesture.

An A/B comparison needs a stable outcome as well as a timing difference.
Check that both variants save, cancel, move, resize, and display charts correctly.
If a change improves only a helper benchmark while the browser frame intervals remain unchanged, report the helper result without claiming smoother interaction.

Check the following boundaries for interaction changes:

- Entry, first movement, continuous movement, release, exit, and saved-layout reload.
- One movement followed by a pause, movement below the drag threshold, quick release, and cancellation.
- Horizontal and vertical resize, affected neighbors, and supported compaction modes.
- A narrow scene with an open side panel, plus a wide scene.
- A full scroll and return, including mounted content, memory, and request counts.
- A fast jump to the middle of a cold dashboard, including frame time, placeholder duration, and query queue wait.
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
