# DataDrivenFunnel Component

A data-driven funnel visualization component that accepts direct data instead of requiring a funnel query. This allows reusing the funnel visualization logic in contexts where you have the data but not a query, such as in experiments or other custom use cases.

## Files Created

- `DataDrivenFunnel.tsx` - Main component with React context
- `funnelDataUtils.ts` - Data processing utilities extracted from funnelDataLogic
- `DataDrivenFunnelBarVertical.tsx` - Vertical bar chart implementation
- `DataDrivenFunnelBarHorizontal.tsx` - Horizontal bar chart implementation  
- `DataDrivenFunnelHistogram.tsx` - Time-to-convert histogram implementation
- `DataDrivenStepBars.tsx` - Step bar visualization components
- `DataDrivenStepBarLabels.tsx` - Breakdown labels component
- `DataDrivenStepLegend.tsx` - Step legend component
- `DataDrivenFunnelExample.tsx` - Usage examples

## Usage

### Basic Usage

```tsx
import { DataDrivenFunnel } from 'scenes/funnels/DataDrivenFunnel'
import { FunnelVizType, FunnelLayout } from '~/types'

function MyComponent() {
  const funnelSteps = [
    {
      action_id: 'step1',
      name: 'Landing Page Visit',
      order: 0,
      count: 1000,
      type: EntityType.EVENTS,
      average_conversion_time: null,
      median_conversion_time: null,
    },
    {
      action_id: 'step2',
      name: 'Sign Up',
      order: 1,
      count: 650,
      type: EntityType.EVENTS,
      average_conversion_time: 120,
      median_conversion_time: 90,
    },
    // ... more steps
  ]

  return (
    <DataDrivenFunnel
      steps={funnelSteps}
      vizType={FunnelVizType.Steps}
      layout={FunnelLayout.vertical}
      showPersonsModal={false}
    />
  )
}
```

### With Breakdowns

```tsx
const stepWithBreakdown = {
  action_id: 'step2',
  name: 'Sign Up',
  order: 1,
  count: 650,
  type: EntityType.EVENTS,
  nested_breakdown: [
    {
      action_id: 'step2',
      name: 'Sign Up',
      order: 1,
      count: 400,
      type: EntityType.EVENTS,
      breakdown_value: 'organic',
    },
    {
      action_id: 'step2',
      name: 'Sign Up',
      order: 1,
      count: 250,
      type: EntityType.EVENTS,
      breakdown_value: 'paid',
    },
  ],
}
```

### Time-to-Convert Histogram

```tsx
const timeConversionData = {
  bins: [
    [0, 50],    // 0-60s: 50 conversions
    [60, 120],  // 60-120s: 120 conversions
    [120, 200], // 120-180s: 200 conversions
    // ... more bins
  ],
}

<DataDrivenFunnel
  steps={funnelSteps}
  vizType={FunnelVizType.TimeToConvert}
  timeConversionData={timeConversionData}
/>
```

## Props

### DataDrivenFunnelProps

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `steps` | `FunnelStepWithNestedBreakdown[]` | Required | Raw funnel step data |
| `vizType` | `FunnelVizType` | `FunnelVizType.Steps` | Visualization type |
| `layout` | `FunnelLayout` | `FunnelLayout.vertical` | Layout for steps visualization |
| `stepReference` | `FunnelStepReference` | `FunnelStepReference.total` | Step reference for conversion calculations |
| `hiddenLegendBreakdowns` | `string[]` | `[]` | Breakdowns to hide from legend |
| `disableBaseline` | `boolean` | `false` | Disable baseline for experiments |
| `timeConversionData` | `FunnelsTimeConversionBins` | `undefined` | Time conversion data for histogram |
| `showPersonsModal` | `boolean` | `true` | Show persons modal on click |
| `inCardView` | `boolean` | `false` | Render in card view |
| `inSharedMode` | `boolean` | `false` | Render in shared mode |

## Data Structure

### FunnelStepWithNestedBreakdown

```typescript
interface FunnelStepWithNestedBreakdown extends FunnelStep {
  nested_breakdown?: FunnelStep[]
}

interface FunnelStep {
  action_id: string
  name: string
  custom_name?: string | null
  order: number
  count: number
  type: EntityType
  average_conversion_time: number | null
  median_conversion_time: number | null
  breakdown?: BreakdownKeyType
  breakdown_value?: BreakdownKeyType
}
```

## Integration with Experiments

For experiments, you can convert experiment results to the expected format:

```tsx
function ExperimentFunnelView({ experimentResults }) {
  const funnelSteps = experimentResults.insight.map((variantSteps, variantIndex) => {
    return variantSteps.map(step => ({
      ...step,
      breakdown_value: experimentResults.variants[variantIndex].key,
    }))
  })

  return (
    <DataDrivenFunnel
      steps={funnelSteps}
      vizType={FunnelVizType.Steps}
      layout={FunnelLayout.vertical}
      disableBaseline={true}
    />
  )
}
```

## Benefits

1. **Reusability** - Use funnel visualizations without needing a funnel query
2. **Consistency** - Same look and behavior as query-based funnels
3. **Flexibility** - Works with any data source (experiments, APIs, etc.)
4. **Performance** - No query execution overhead
5. **Customization** - Full control over data processing and display

## Architecture

The component uses a React context to provide processed data to child components:

1. **DataDrivenFunnel** - Main component that processes raw data
2. **FunnelDataContext** - React context for sharing processed data
3. **Visualization Components** - Reusable components for different chart types
4. **Data Processing** - Utilities extracted from funnelDataLogic

This architecture allows for easy extension and customization while maintaining consistency with the existing funnel visualization system.