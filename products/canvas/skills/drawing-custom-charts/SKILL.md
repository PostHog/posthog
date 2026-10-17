---
name: drawing-custom-charts
description: >
  Draw a chart in a PostHog canvas that `@posthog/quill-charts` does not ship, or add marks a stock
  chart does not have: annotations, callouts, goal bands, incident windows, hover-linked readouts,
  or a whole new shape such as a bump chart, ridgeline, waterfall, sunburst, force graph, beeswarm,
  streamgraph or treemap. Use when a canvas request names a chart type outside the quill-charts
  table, asks to mark or annotate a chart, or needs a visualization built with d3. Covers the
  ladder from stock chart to custom overlay to the `Chart` core to raw d3, the themed tooltip and
  sizing kit, and the mistakes that only show at runtime.
---

# Drawing custom charts

`@posthog/quill-charts` is a `<canvas>` renderer with d3 underneath.
Every stock chart is a thin layer on a public core, and the overlay layer above the canvas is React.
That gives three seams for drawing what the library does not ship, and `d3` is already an admitted canvas import for the geometry.
Load `building-react-quill-canvases` first for the canvas contract, the allowed imports and the stock chart table; this skill starts where that table ends.

## Climb the ladder, stop at the first rung that fits

Each rung costs more and loses more of the free behavior, so take the lowest one that answers the request.

1. **A stock chart.** The table in `building-react-quill-canvases/references/platform-libraries.md` is wider than it looks. A rank list is a `BarList`, a share of a whole is a `ProportionBar`, bars and lines together are a `ComboChart`, a distribution is a `BoxPlot`, a comparison between two points is a `SlopeChart`. Stock charts bring legends, value labels, drag-to-zoom and click payloads.
2. **A stock chart plus an overlay.** Most "custom" requests are a stock chart with one more mark on it: a target line, a release marker, an incident window, a callout on the peak, a readout that follows the hover. The overlay layer is React, positioned with the chart's own scales. Read [references/overlays.md](references/overlays.md). No drawing code, and the tooltip, hover and axes stay stock.
3. **The `Chart` core.** When the shape itself is new but the data still sits on a category axis (one label per x position), give `Chart` three functions, `createScales`, `drawStatic` and `drawHover`, and keep the stock axes, hover resolution, tooltip and overlays. Read [references/custom-shapes.md](references/custom-shapes.md).
4. **Raw d3 with the chart theme.** When there is no category axis (hierarchy, network, map, swarm), lay out with d3 and render it yourself, in SVG or your own `<canvas>`. Take every color from `useChartTheme()` so it sits beside the stock charts without looking foreign. Same reference.

Say which rung you took in the reply, in one line. "Stock bar chart with a `ReferenceLine` for the target" tells the reader what they can edit later.

## The kit

Three small pieces come up on every rung above the first.
Copy them into the canvas as `src/chart-kit.tsx` rather than rewriting them each time; the full file is in [references/gallery.md](references/gallery.md#tiptsx).

- **The palette.** `const theme = useChartTheme()`. `theme.colors[i]` is the PostHog data palette in the right light or dark variant; `theme.axisColor`, `theme.gridColor`, `theme.backgroundColor`, `theme.tooltipBackground` and `theme.tooltipColor` are the rest. Never a hardcoded hex, and never a UI token such as `bg-primary` for data.
- **The tooltip.** Outside a chart, render a div at the cursor colored with `theme.tooltipBackground` and `theme.tooltipColor`, with `TooltipSwatch` from `@posthog/quill-charts` for the color dot. That is the same box the stock charts show. `TooltipSurface` and `DefaultTooltip` read the chart context and throw outside a `Chart`, so use them only inside one. Never an SVG `<title>`: it shows after a delay, only while the mouse is still, and in the browser's own style.
- **Sizing.** A chart fills its parent. Wrap it in `<div className="flex h-[300px] flex-col">`. Raw d3 components measure their container with a `ResizeObserver` and render nothing until it has a size.

## Rules that only show at runtime

The build reports syntax and import errors. It does not run the canvas, so these reach the user as a blank card or a crash unless you follow them:

- `TooltipSurface`, `DefaultTooltip`, `ReferenceLine`, `HighlightedRange`, `useChartLayout` and `useChartHover` work only as children of a chart. Outside one they throw `useChartLayout must be used inside a chart component`.
- A parent without `flex flex-col` and a height gives a core chart zero height. A raw d3 component with no measured size renders nothing.
- `series[i].color` is resolved from the palette by the time `drawStatic` runs. Do not pick colors in draw code.
- The `Chart` core resolves hover along `labels`. A custom shape with no label per x position gets no tooltip; that is the signal to drop to rung 4.
- A force simulation keeps running after unmount unless the effect cleanup calls `simulation.stop()`.
- `d3` is the full build except `d3-sankey`. Use quill's `SankeyChart` once it is in the platform version; until then a Sankey is a raw d3 layout you write.

## References

- [references/overlays.md](references/overlays.md): the overlay layer. `ReferenceLine`, `HighlightedRange`, and custom overlays built on `useChartLayout()` and `useChartHover()`, with three worked examples.
- [references/custom-shapes.md](references/custom-shapes.md): the `Chart` core contract and the raw d3 pattern, each with a worked example.
- [references/gallery.md](references/gallery.md): six verified shapes to copy and adapt: bump chart, ridgeline, waterfall, sunburst, force graph, beeswarm, plus the shared kit file.
