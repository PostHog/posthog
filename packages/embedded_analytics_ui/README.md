# @posthog/embedded-analytics-ui

React components for PostHog's embedded web analytics API.

## Development

```bash
# Install dependencies
pnpm install

# Start development server
pnpm dev

# Run Storybook
pnpm storybook

# Build library
pnpm build

# Lint and format
pnpm lint
pnpm format
```

## Deployment

### Storybook on Vercel

This project is configured to deploy Storybook to Vercel automatically.

#### First-time setup:

1. Install Vercel CLI:
   ```bash
   npm i -g vercel
   ```

2. Login to Vercel:
   ```bash
   vercel login
   ```

3. Deploy to Vercel:
   ```bash
   pnpm deploy-storybook
   ```

#### Automatic deployments:

- Connect your GitHub repository to Vercel
- Vercel will automatically deploy on every push to main
- Build command: `pnpm build-storybook`
- Output directory: `storybook-static`

#### Manual deployment:

```bash
# Build and deploy to production
pnpm deploy-storybook

# Or build locally first
pnpm build-storybook
vercel --prod
```

## Components

- **Overview**: Display key metrics with change indicators
- **Graph**: Line charts with current vs previous period comparison
- **Table**: Sortable, paginated tables with optional fill bars

## Usage

```tsx
import { Overview, Graph, Table } from '@posthog/embedded-analytics-ui';

// Use components with your PostHog analytics data
<Overview data={metrics} loading={false} />
<Graph data={chartData} loading={false} />
<Table data={tableData} loading={false} />
```

## Customization

### CSS Variables

All colors and styling can be customized using CSS variables with the `--ph-embed-` prefix:

```css
:root {
  /* Chart colors */
  --ph-embed-chart-line-color: 220 100% 50%; /* Blue line color */
  --ph-embed-chart-line-color-muted: 220 100% 30%; /* Muted line color */
  --ph-embed-chart-grid: 240 4.9% 83.9%; /* Grid lines */
  --ph-embed-chart-text: 240 10% 3.9%; /* Axis text */
  
  /* Metric colors */
  --ph-embed-positive: 120 100% 30%; /* Green for positive changes */
  --ph-embed-negative: 0 100% 50%; /* Red for negative changes */
  --ph-embed-neutral: 240 3.8% 46.1%; /* Gray for neutral */
  
  /* Table fill color */
  --ph-embed-table-fill-color: 280 100% 50%; /* Purple fill bars */
}

/* Dark mode automatically supported */
.dark {
  --ph-embed-chart-line-color: 220 100% 70%;
  --ph-embed-chart-text: 0 0% 95%;
  /* ... other dark mode overrides */
}
```

### Available CSS Variables

- `--ph-embed-chart-line-color`: Primary line color for charts
- `--ph-embed-chart-line-color-muted`: Secondary/previous period line color
- `--ph-embed-chart-grid`: Grid line color
- `--ph-embed-chart-text`: Axis labels and text color
- `--ph-embed-positive`: Color for positive metric changes
- `--ph-embed-negative`: Color for negative metric changes
- `--ph-embed-neutral`: Color for neutral text
- `--ph-embed-table-fill-color`: Background color for table fill bars