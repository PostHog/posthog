# Experiment Metrics View Code Review

## Overview
This review analyzes the iterative changes made to the experiment metrics view in `frontend/src/scenes/experiments/MetricsView/new/`. The refactoring introduces several new components and reorganizes the existing architecture to support both tabular and chart-based views.

## Key Changes Summary
- **17 files modified** with 1,173 additions and 86 deletions
- **New components**: ChartAxis, ChartCell, ChartCellTooltip, ChartGradients, MetricRowGroup, MetricsTable, TableHeader, TickLabels, VariantRow
- **Enhanced components**: Chart, GridLines, MetricRow, Metrics, ConfidenceIntervalAxis
- **New utilities**: useAxisScale hook, additional constants

## Major Issues & Recommendations

### 1. **Hardcoded Values That Should Be Constants**

#### 🔴 **HIGH PRIORITY - Magic Numbers**
- **Line widths scattered throughout**: `1.25`, `0.75`, `2` (strokeWidth values)
- **Border radius values**: `3` (rx/ry) in `ChartCell.tsx:114-115`
- **Z-index values**: `z-[100]` in `ChartCellTooltip.tsx:60`
- **Opacity values**: `0.7`, `0.8` mixed with constants

```typescript
// ChartCell.tsx:85-87 - Hardcoded stroke widths
zeroLineWidth={1.25}
gridLineWidth={0.75}

// ChartCell.tsx:126 - Hardcoded stroke width
strokeWidth={2}

// ChartCellTooltip.tsx:37-40 - Hardcoded padding
const padding = 8
```

**Recommendation**: Extract these to constants file:
```typescript
// constants.ts - Missing constants
export const STROKE_WIDTHS = {
  ZERO_LINE: 1.25,
  GRID_LINE: 0.75,
  DELTA_MARKER: 2,
} as const

export const BORDER_RADIUS = 3
export const TOOLTIP_Z_INDEX = 100
export const TOOLTIP_PADDING = 8
```

#### 🔴 **HIGH PRIORITY - CSS Classes Duplication**
Multiple components repeat similar table cell styling patterns:

```typescript
// ChartCell.tsx:54-56 & 64-67 - Repeated pattern
className={`min-w-[400px] p-0 align-top text-center relative ${
  isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'
} ${isLastRow ? 'border-b border-border-bold' : ''}`}

// VariantRow.tsx:71-73 & 88-91 - Similar pattern
className={`w-1/5 min-h-[60px] border-r border-border-bold p-3 align-top text-left relative ${
  !isLastMetric ? 'border-b' : ''
} ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'}`}
```

**Recommendation**: Create reusable styling utilities:
```typescript
// utils/tableStyles.ts
export const getTableCellClasses = (options: {
  isAlternatingRow: boolean
  isLastRow?: boolean
  isLastMetric?: boolean
  width?: string
}) => {
  // Centralized table cell styling logic
}
```

### 2. **Duplicate Logic That Should Be Consolidated**

#### 🔴 **HIGH PRIORITY - Interval Calculation Logic**
Multiple components repeat the same interval calculation pattern:

```typescript
// ChartCell.tsx:38-40
const interval = getVariantInterval(variantResult)
const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]
const delta = interval ? (interval[0] + interval[1]) / 2 : 0

// ChartCellTooltip.tsx:22-24
const interval = getVariantInterval(variantResult)
const [lower, upper] = interval ? [interval[0], interval[1]] : [0, 0]
const intervalPercent = interval ? `[${(lower * 100).toFixed(2)}%, ${(upper * 100).toFixed(2)}%]` : 'N/A'
```

**Recommendation**: Create a custom hook:
```typescript
// hooks/useVariantInterval.ts
export function useVariantInterval(variantResult: ExperimentVariantResult) {
  return useMemo(() => {
    const interval = getVariantInterval(variantResult)
    return {
      interval,
      lower: interval?.[0] ?? 0,
      upper: interval?.[1] ?? 0,
      delta: interval ? (interval[0] + interval[1]) / 2 : 0,
      intervalPercent: interval ? `[${(interval[0] * 100).toFixed(2)}%, ${(interval[1] * 100).toFixed(2)}%]` : 'N/A'
    }
  }, [variantResult])
}
```

#### 🔴 **HIGH PRIORITY - Tooltip Positioning Logic**
`ChartCellTooltip.tsx:27-46` contains complex positioning logic that could be extracted:

```typescript
// ChartCellTooltip.tsx:27-46
useEffect(() => {
  if (isVisible && containerRef.current && tooltipRef.current) {
    const containerRect = containerRef.current.getBoundingClientRect()
    const tooltipRect = tooltipRef.current.getBoundingClientRect()
    
    // Complex positioning logic...
  }
}, [isVisible])
```

**Recommendation**: Extract to custom hook:
```typescript
// hooks/useTooltipPosition.ts
export function useTooltipPosition(isVisible: boolean, containerRef: RefObject<HTMLElement>, tooltipRef: RefObject<HTMLElement>) {
  // Centralized tooltip positioning logic
}
```

### 3. **Architecture & Structure Issues**

#### 🔴 **HIGH PRIORITY - Component Responsibilities**
`ChartCell.tsx` is handling too many concerns:
- Data processing (`getVariantInterval`, interval calculations)
- Styling logic (alternating rows, borders)
- Chart rendering (SVG generation)
- Tooltip management

**Recommendation**: Split into focused components:
```typescript
// ChartCellContent.tsx - Pure rendering
// ChartCellContainer.tsx - Layout and styling
// useChartCellData.ts - Data processing hook
```

#### 🔴 **HIGH PRIORITY - Inconsistent Default Parameters**
Different components handle default parameters inconsistently:

```typescript
// useAxisScale.ts:8-12
export function useAxisScale(
  chartRadius: number,
  viewBoxWidth: number = 800,  // Default in function signature
  edgeMargin: number = 20
)

// GridLines.tsx:13-16  
interface GridLinesProps {
  viewBoxWidth?: number
  // ...
}
// Default in destructuring: viewBoxWidth = 800
```

**Recommendation**: Centralize defaults in constants and use consistent patterns:
```typescript
// constants.ts
export const DEFAULTS = {
  VIEW_BOX_WIDTH: 800,
  EDGE_MARGIN: 20,
} as const

// Use consistently across components
viewBoxWidth = DEFAULTS.VIEW_BOX_WIDTH
```

#### 🔴 **HIGH PRIORITY - Missing Type Safety**
Several components use loose typing:

```typescript
// VariantRow.tsx:18-19
variantResult: ExperimentVariantResult | ExperimentStatsBase
testVariantResult: ExperimentVariantResult | null
```

**Recommendation**: Create more specific union types:
```typescript
// types/experiment.ts
export type ChartVariantResult = ExperimentVariantResult | ExperimentStatsBase
export type TestVariantResult = ExperimentVariantResult | null
```

### 4. **Minor Issues & Improvements**

#### 🔶 **MEDIUM PRIORITY - Edge Threshold Duplication**
`edgeThreshold = 0.06` appears in multiple components:
- `GridLines.tsx:31`
- `TickLabels.tsx:31`

**Recommendation**: Extract to constants.

#### 🔶 **MEDIUM PRIORITY - Inconsistent Naming**
- `chartRadius` vs `maxAbsValue` for the same concept
- `viewBoxWidth` vs `VIEW_BOX_WIDTH` inconsistency
- `isAlternatingRow` vs `isLastRow` naming pattern

#### 🔶 **MEDIUM PRIORITY - Missing Error Boundaries**
Complex components like `ChartCellTooltip` lack error handling for edge cases.

#### 🔶 **MEDIUM PRIORITY - Performance Optimizations**
- `ChartCellTooltip.tsx:108` contains inline calculations that could be memoized
- `useAxisScale` could benefit from `useCallback` optimization (already implemented)

## Positive Patterns

### ✅ **Well-Structured Abstractions**
- `useAxisScale` hook provides good encapsulation
- `ChartGradients` component handles gradient logic cleanly
- `TickLabels` and `GridLines` are well-focused components

### ✅ **Good Type Safety**
- Strong TypeScript usage throughout
- Clear interface definitions
- Proper use of union types for experiment results

### ✅ **Consistent Constants Usage**
- Good use of constants file for sizing values
- Centralized opacity and height constants

### ✅ **Proper Separation of Concerns**
- Color logic separated into `useChartColors` hook
- Utility functions well-organized in `shared/utils.ts`
- Components focused on single responsibilities (mostly)

## Recommendations Summary

### Immediate Actions (Before Building Further)
1. **Extract hardcoded values** to constants file
2. **Create reusable table styling utilities**
3. **Consolidate interval calculation logic** into custom hook
4. **Split ChartCell component** into focused sub-components
5. **Standardize default parameter patterns**

### Medium-Term Improvements
1. **Add error boundaries** for complex components
2. **Implement performance optimizations** for calculations
3. **Improve type safety** with more specific union types
4. **Create comprehensive testing** for new components

### Code Quality Foundation
The refactoring shows good architectural thinking with proper component separation and hook usage. The main issues are around code duplication and hardcoded values, which are easily addressable. Once these are resolved, this will provide a solid foundation for future development.

## Files Requiring Attention
- `ChartCell.tsx` - Needs component splitting and constant extraction
- `ChartCellTooltip.tsx` - Extract positioning logic and add error handling
- `VariantRow.tsx` - Consolidate styling logic and improve type safety
- `constants.ts` - Add missing constants for stroke widths, borders, etc.
- `GridLines.tsx` & `TickLabels.tsx` - Standardize edge threshold handling