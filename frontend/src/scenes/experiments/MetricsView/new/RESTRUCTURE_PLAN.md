# Metrics View Restructure Plan

## Overview
Restructure the experiments metrics view to use a proper HTML table foundation instead of the current SVG-based layout. This will improve maintainability, accessibility, and make it easier to add new columns and features.

## Current Issues
- Complex SVG positioning calculations
- Difficult alignment between variant info and chart bars
- Hard to maintain horizontal separators across components
- Poor semantic structure for accessibility
- Tight coupling between layout and chart rendering

## Proposed Table Structure

### Table Layout
```
| Metric                    | Baseline      | Variant       | Chart                    |
|---------------------------|---------------|---------------|--------------------------|
| Conversion Rate (rowspan) | control       | test          | ■■■■■■■■ confidence bar  |
|                           | 1,234 samples | 1,456 samples |                          |
|                           | 12.3%         | 15.7%         |                          |
|---------------------------|---------------|---------------|--------------------------|
| Revenue (rowspan)         | control       | test          | ■■■■■■■■ confidence bar  |
|                           | 1,234 samples | 1,456 samples |                          |
|                           | $45.67        | $52.10        |                          |
```

### Column Specifications

1. **Metric Column** (spans all variant rows for that metric)
   - Metric name and type badge
   - Edit/delete controls
   - Significance indicators
   - Details modal trigger

2. **Baseline Column** (typically control variant)
   - Variant name
   - Sample count (humanFriendlyNumber)
   - Primary value (conversion rate, mean, etc.)
   - Optional: confidence interval text

3. **Variant Column(s)** (one column per test variant)
   - Variant name  
   - Sample count
   - Primary value
   - Statistical significance indicators (p-value, chance to win)

4. **Chart Column**
   - Confidence interval visualization (SVG within table cell)
   - Maintains current violin plots for Bayesian results
   - Horizontal bars for frequentist results

## Component Architecture

### 1. MetricsTable.tsx
**Responsibility**: Root table container and data coordination
```typescript
interface MetricsTableProps {
  metrics: ExperimentMetric[]
  results: NewExperimentQueryResponse[]
  isSecondary: boolean
  experiment: Experiment
}
```

**Key Features**:
- Renders `<table>` with proper semantic structure
- Calculates shared chart radius across all metrics
- Handles loading and error states
- Manages table-wide styling and responsive behavior

### 2. MetricRowGroup.tsx
**Responsibility**: Handles a single metric and all its variants
```typescript
interface MetricRowGroupProps {
  metric: ExperimentMetric
  result: NewExperimentQueryResponse
  metricIndex: number
  chartRadius: number
  isSecondary: boolean
  variants: string[] // ordered list of variant keys
}
```

**Key Features**:
- Uses `rowspan` for metric column across all variant rows
- Identifies baseline variant (typically 'control')
- Renders one `VariantRow` per variant
- Handles "no data" states

### 3. VariantRow.tsx
**Responsibility**: Single table row for one metric-variant combination
```typescript
interface VariantRowProps {
  variantResult: ExperimentVariantResult
  variantKey: string
  isBaseline: boolean
  isFirstRow: boolean // for rowspan metric column
  metric?: ExperimentMetric // only for first row
  metricIndex: number
  chartRadius: number
  rowIndex: number
  totalRows: number
}
```

**Key Features**:
- Renders metric column only for first row (with rowspan)
- Baseline vs variant conditional styling
- Statistical significance indicators
- Sample counts and primary values

### 4. ChartCell.tsx
**Responsibility**: Chart visualization within table cell
```typescript
interface ChartCellProps {
  variantResult: ExperimentVariantResult
  chartRadius: number
  metricIndex: number
  isSecondary: boolean
  rowIndex: number
  totalRows: number
}
```

**Key Features**:
- SVG chart within table cell
- Maintains current violin/bar chart logic
- Proper tooltip positioning
- Responsive sizing

### 5. TableHeader.tsx
**Responsibility**: Table header with column labels
```typescript
interface TableHeaderProps {
  variants: string[]
}
```

**Key Features**:
- Dynamic variant column headers
- Responsive column sizing
- Sorting controls (future enhancement)

## Data Flow

1. **MetricsTable** receives all metrics and results
2. Calculates shared `chartRadius` across all confidence intervals
3. Identifies unique variants across all metrics
4. Renders **TableHeader** with variant names
5. For each metric, renders **MetricRowGroup**
6. **MetricRowGroup** renders one **VariantRow** per variant
7. Each **VariantRow** includes a **ChartCell** for visualization

## Styling Strategy

### CSS Classes
```scss
.metrics-table {
  width: 100%;
  border-collapse: collapse;
  
  th, td {
    padding: 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  
  .metric-cell {
    width: 20%;
    border-right: 1px solid var(--border);
  }
  
  .variant-cell {
    width: 15%;
    text-align: center;
  }
  
  .chart-cell {
    width: 50%;
    padding: 8px;
  }
}
```

### Responsive Behavior
- Horizontal scroll for narrow screens
- Collapsible variant columns on mobile
- Maintain minimum column widths

## Migration Strategy

### Phase 1: Create New Components
- Build new table-based components alongside existing ones
- Use feature flag to toggle between implementations
- Ensure visual parity with current design

### Phase 2: Data Integration
- Integrate with existing logic (experimentLogic)
- Maintain current props and data flow
- Test with various metric configurations

### Phase 3: Replace Existing
- Remove old Chart.tsx, MetricRow.tsx, ConfidenceIntervalAxis.tsx
- Update Metrics.tsx to use MetricsTable
- Clean up unused constants and utilities

## Questions for Clarification

1. **Baseline Definition**: Should baseline always be 'control' variant, or configurable per metric?

2. **Variant Ordering**: Should variants be ordered alphabetically, by sample size, or maintain experiment definition order?

3. **Chart Column Width**: Should chart column be fixed width or responsive based on confidence interval range?

4. **Mobile Behavior**: How should the table behave on narrow screens? Collapse to cards? Horizontal scroll?

5. **Statistical Display**: Which statistical measures should be prominently displayed in variant columns vs. tooltips?

6. **Empty States**: How should we handle metrics with no variants or missing data?

7. **Accessibility**: Any specific ARIA requirements for screen readers?

## Benefits of This Approach

- **Semantic HTML**: Proper table structure for accessibility
- **Simplified Alignment**: No complex SVG positioning calculations
- **Easy Extensions**: Adding new columns is straightforward
- **Better Maintainability**: Clear separation of concerns
- **Responsive Design**: Native table responsive behavior
- **Performance**: Less complex rendering and calculations
- **Testability**: Easier to test individual table components

## File Structure
```
MetricsView/new/
├── MetricsTable.tsx           # Root table component
├── TableHeader.tsx            # Table header
├── MetricRowGroup.tsx         # Metric + all variants
├── VariantRow.tsx             # Single variant row
├── ChartCell.tsx              # Chart within table cell
├── MetricsTable.scss          # Table-specific styles
└── tableUtils.ts              # Shared utilities
```