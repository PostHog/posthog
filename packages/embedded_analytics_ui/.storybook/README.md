# Storybook for PostHog Embedded Analytics UI

This Storybook contains stories for all the analytics components, showcasing different states and use cases.

## Running Storybook

```bash
pnpm storybook
```

This will start Storybook on [http://localhost:6006](http://localhost:6006).

## Building Storybook

```bash
pnpm build-storybook
```

## What's Included

### Components

1. **Overview** - Key metrics with change indicators
   - Happy state with various number formats
   - Loading state with skeleton loaders
   - Error state with error messages
   - Different data scenarios (with/without previous values)

2. **Graph** - Linear area charts with time series data
   - Happy state with current and previous period data
   - Loading state with skeleton loader
   - Error state with error messages
   - Various time periods and data volumes

3. **Table** - Data tables with sorting and pagination
   - Happy state with fill bars and interactive features
   - Loading state with skeleton rows
   - Error state with error messages
   - Different data types and scenarios

### Features Demonstrated

- **Dark/Light Mode**: Use the theme toggle in the toolbar
- **Responsive Design**: Use the viewport controls to test different screen sizes
- **Interactive Elements**: Click handlers, sorting, pagination
- **Loading States**: Skeleton loaders for all components
- **Error States**: Error handling with detailed messages
- **Accessibility**: Keyboard navigation and screen reader support

### Controls

Each story includes controls where applicable:
- **Overview**: Toggle loading states, modify data
- **Graph**: Adjust chart height, modify data
- **Table**: Pagination controls, sorting states

### Background Colors

Use the background controls to test components on light and dark backgrounds.