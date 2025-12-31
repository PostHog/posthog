# Pipeline Platform

This directory contains the pipeline registry infrastructure that enables configurable pipeline selection at runtime.

## Files

- **types.ts** - Generic type definitions for pipeline registries (`PipelineFactory`, `PipelineRegistry`, etc.)
- **registry.ts** - Global registry mapping pipeline names to their implementations
- **selector.ts** - Runtime pipeline selection based on configuration

## Configuration

Pipelines are selected via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `INGESTION_PIPELINE_NAME` | Pipeline name (e.g., `general`) | `general` |
| `INGESTION_PIPELINE_LANE` | Lane within pipeline (e.g., `default`, `overflow`) | `default` |
| `INGESTION_PIPELINE_IMPLEMENTATION` | Implementation within lane | `default` |

## Adding a New Pipeline

1. Create a directory for your pipeline (e.g., `ingestion/replay/`)
2. Define your pipeline's `Input`, `Context`, and `Config` types
3. Create a `registry.ts` exporting a `PipelineRegistry<Input, Context, Config>`
4. Add your pipeline to `platform/registry.ts`:

```typescript
import { pipeline as replayPipeline } from '../replay'

export const pipelines = {
    general: generalPipeline,
    replay: replayPipeline,
}
```

## Registry Structure

Each pipeline has lanes, and each lane has implementations:

```text
pipelines
└── general
    └── lanes
        ├── default
        │   └── implementations
        │       └── default: createMainPipeline
        ├── overflow
        │   └── implementations
        │       └── default: createMainPipeline
        ├── historical
        └── async
```

The `default` key is required at both the lane and implementation level.
