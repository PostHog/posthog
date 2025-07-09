# Tick Values Implementation Technical Reference

## Overview
This document provides a comprehensive technical reference for how tick values are implemented in the GrowthBook experiment results table graphs. The implementation uses dynamic tick value generation with SVG-based rendering and adaptive scaling.

## Key Components

### 1. AlignedGraph Component (`/components/Experiment/AlignedGraph.tsx`)
The primary graph component that handles tick value generation and rendering.

### 2. PercentGraph Component (`/components/Experiment/PercentGraph.tsx`)
A wrapper component that passes props to `AlignedGraph` with experiment-specific data.

### 3. Domain Calculation (`/services/experiments.ts`)
Contains the `useDomain` function that calculates the data bounds for the graph.

## Dynamic Tick Value Generation

### Tick Count Calculation
```typescript
const numTicks = Math.max(graphWidth / 75, 3);
```
- **Algorithm**: One tick per 75 pixels of graph width
- **Minimum**: 3 ticks regardless of graph width
- **Dynamic**: Automatically adjusts based on available space

### Tick Value Formatting
```typescript
const tickFormat = (v: number) => {
  return metricForFormatting
    ? getExperimentMetricFormatter(metricForFormatting, getFactTableById)(
        v as number,
        metricFormatterOptions
      )
    : !percent
    ? numberFormatter.format(v)
    : domainWidth < 0.05
    ? smallPercentFormatter.format(v)
    : percentFormatter.format(v);
};
```

**Formatting Logic**:
- **Metric-specific**: Uses custom formatters for different metric types
- **Currency**: Supports currency formatting with organization settings
- **Percentage**: Two levels of precision based on domain width
  - Small domain (< 0.05): 1 decimal place
  - Large domain (≥ 0.05): 0 decimal places
- **Large numbers**: Compact notation for values > 5000

## SVG Implementation Details

### Library Dependencies
- **@visx/axis**: Axis rendering and tick generation
- **@visx/grid**: Grid line rendering
- **@visx/scale**: Linear scale mapping
- **@visx/responsive**: Responsive container handling

### Scale Configuration
```typescript
const xScale = scaleLinear({
  domain: domain,
  range: [0, graphWidth],
});
```
- **Domain**: Data bounds calculated from confidence intervals
- **Range**: Pixel coordinates from 0 to graph width
- **Type**: Linear scale for consistent spacing

### Axis Components

#### Grid Lines
```typescript
<GridColumns
  scale={xScale}
  width={graphWidth}
  height={visHeight}
  stroke={gridColor}
  numTicks={numTicks}
/>
```
- **Purpose**: Vertical grid lines aligned with tick marks
- **Styling**: Uses CSS custom property `--slate-a3` for color

#### Zero Line
```typescript
<AxisLeft
  orientation={Orientation.left}
  left={xScale(0) - zeroLineWidth / 2 + zeroLineOffset}
  scale={yScale}
  stroke={zeroLineColor}
  strokeWidth={zeroLineWidth}
  numTicks={0}
/>
```
- **Position**: Dynamically positioned at x=0 in data coordinates
- **Styling**: Uses `--color-text-low` CSS variable

#### Main Axis
```typescript
<Axis
  orientation={Orientation.top}
  top={visHeight}
  scale={xScale}
  tickLength={5}
  tickFormat={tickFormat}
  tickStroke={axisColor}
  tickLabelProps={tickLabelProps}
  numTicks={numTicks}
  hideAxisLine={true}
/>
```
- **Position**: Top orientation, positioned at bottom of graph
- **Ticks**: Generated automatically by visx based on `numTicks`
- **Labels**: Custom positioning with edge detection

## Scaling and Positioning

### Domain Calculation
```typescript
export function useDomain(
  variations: ExperimentReportVariationWithIndex[],
  rows: ExperimentTableRow[],
  differenceType: DifferenceType
): [number, number] {
  // Iterate through all variations and metrics
  // Find min/max confidence interval bounds
  // Ensure domain includes zero
  // Return [lowerBound, upperBound]
}
```

**Algorithm**:
1. Initialize bounds at 0
2. Iterate through all experiment variations
3. Extract confidence intervals from statistics
4. Update bounds with min/max values
5. Ensure zero is included in domain
6. Return final bounds

### Domain Padding
```typescript
const domainPadding = (domain[1] - domain[0]) * 0.1;
const leftDomain = domain[0] - domainPadding;
const rightDomain = domain[1] + domainPadding;
```
- **Padding**: 10% of domain range on each side
- **Purpose**: Prevents graph elements from touching edges

### Tick Label Positioning
```typescript
const tickLabelProps = (value) => {
  const currentX = xScale(value);
  const pos = currentX / graphWidth;
  if (pos < 0.06 || pos > 0.94) {
    return { display: "none" };
  }
  return {
    fill: axisColor,
    fontSize: 12,
    y: -10,
    x: currentX + 3,
    fontFamily: "sans-serif",
    textAnchor: "middle",
  };
};
```

**Edge Detection**:
- **Hide labels**: Within 6% of left/right edges
- **Prevents overlap**: Avoids label collision at boundaries
- **Positioning**: 3px offset from tick mark, centered alignment

## Responsive Behavior

### Graph Width Calculation
```typescript
function onResize() {
  const tableWidth = tableContainerRef.current?.clientWidth;
  const firstRowCells = tableContainerRef.current?.querySelectorAll(
    "#main-results thead tr:first-child th:not(.graph-cell)"
  );
  let totalCellWidth = 0;
  for (let i = 0; i < firstRowCells.length; i++) {
    totalCellWidth += firstRowCells[i].clientWidth;
  }
  const graphWidth = tableWidth - totalCellWidth;
  setGraphCellWidth(Math.max(graphWidth, 200));
}
```

**Responsive Strategy**:
- **Dynamic width**: Calculated from available table space
- **Minimum width**: 200px enforced
- **Tick adaptation**: Tick count adjusts with width changes
- **Debounced resize**: Uses 1000ms debounce to prevent excessive recalculation

### Mobile Optimization
```typescript
style={{
  width: (globalThis.window?.innerWidth ?? 900) < 900
    ? graphCellWidth
    : undefined,
  minWidth: (globalThis.window?.innerWidth ?? 900) >= 900
    ? graphCellWidth
    : undefined,
}}
```
- **Breakpoint**: 900px screen width
- **Mobile**: Fixed width below breakpoint
- **Desktop**: Minimum width above breakpoint

## Integration with Results Table

### Data Flow
1. **Domain calculation**: `useDomain` hook calculates bounds from all experiment data
2. **Graph rendering**: `AlignedGraph` receives domain and renders ticks
3. **Tick generation**: visx automatically generates tick values within domain
4. **Formatting**: Custom formatters applied based on metric type
5. **Positioning**: Tick labels positioned with edge detection

### Graph Types
- **Axis only**: Shows only tick marks and grid (baseline row)
- **With data**: Shows confidence intervals and statistical significance
- **Pill bars**: Rectangular confidence intervals (frequentist)
- **Violin plots**: Probability distributions (Bayesian)

## Performance Considerations

### Debouncing
- **Resize events**: 1000ms debounce prevents excessive recalculation
- **Component updates**: Memoized domain calculation with dependency array

### SVG Optimization
- **Gradient definitions**: Reused via IDs to minimize DOM
- **Mask usage**: Efficient clipping for confidence intervals
- **Minimal DOM**: Single SVG element per graph

## Customization Points

### Styling Variables
```scss
--color-text-mid: axis labels color
--color-text-low: zero line color
--slate-a3: grid line color
--jade-10/11: positive significance colors
--red-10/11: negative significance colors
```

### Configuration Constants
```typescript
const ROW_HEIGHT = 56;
const METRIC_LABEL_ROW_HEIGHT = 44;
const SPACER_ROW_HEIGHT = 6;
```

### Formatter Options
- **Currency**: Configurable currency display
- **Precision**: Adaptive decimal places
- **Compact notation**: For large numbers
- **Percentage**: Context-sensitive formatting

## Implementation Notes

### Key Features
- **Automatic tick generation**: No manual tick definition required
- **Adaptive formatting**: Context-aware number formatting
- **Responsive design**: Works across screen sizes
- **Edge case handling**: Prevents label overlap and overflow
- **Performance optimized**: Debounced calculations and efficient rendering

### Dependencies
- React 18+ for hooks and components
- visx library for SVG graph primitives
- CSS custom properties for theming
- Intl.NumberFormat for localized formatting

This implementation provides a robust, scalable solution for dynamic tick value generation in data visualization contexts.