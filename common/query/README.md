# @posthog/query

The `@posthog/query` workspace package exposes the PostHog query renderer that powers the `/render_query` endpoint.
It re-exports the `Query` component together with helper types, schema utilities, and the `RenderQueryApp` that we
mount inside embedded frames.

## Installation

This package lives in the monorepo and is available via the PNPM workspace. Add it as a dependency:

```bash
pnpm add @posthog/query --filter <your-package>
```

The package only declares `react` and `react-dom` as peer dependencies because those are required at runtime. All other
imports are resolved from the PostHog frontend source tree.

## Usage

```tsx
import { Query, type QueryProps } from '@posthog/query'
import type { Node } from '@posthog/query'

const query: Node = {
    kind: 'DataTableNode',
    source: {
        kind: 'EventsQuery',
        select: ['count()'],
    },
}

export function ExampleQuery(): JSX.Element {
    return <Query query={query} readOnly embedded />
}
```

To bootstrap the iframe renderer that powers `/render_query`, import the dedicated entry point:

```tsx
import { RenderQueryApp } from '@posthog/query/render-query-app'
```

## Demos & examples

The `examples/` directory contains a couple of lightweight demos that illustrate how to communicate with the embedded
renderer and how to render queries directly inside a React tree.
