import { PluginEvent } from '@posthog/plugin-scaffold'

import { createHandleClientIngestionWarningStep } from '../event-processing/handle-client-ingestion-warning-step'
import { PipelineBuilder, StartPipelineBuilder } from '../pipelines/builders/pipeline-builders'

export interface ClientIngestionWarningSubpipelineInput {
    event: PluginEvent
}

export function createClientIngestionWarningSubpipeline<
    TInput extends ClientIngestionWarningSubpipelineInput,
    TContext,
>(builder: StartPipelineBuilder<TInput, TContext>): PipelineBuilder<TInput, void, TContext> {
    return builder.pipe(createHandleClientIngestionWarningStep())
}
