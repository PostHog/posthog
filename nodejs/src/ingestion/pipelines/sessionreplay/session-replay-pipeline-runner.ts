import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import {
    SessionReplayPipeline,
    SessionReplayPipelineConfig,
    runSessionReplayPipeline,
} from '~/ingestion/pipelines/sessionreplay'

import { AdmittedBatch } from './batch-stages'
import { BatchCommitter, StagedBatchRunner } from './staged-batch'

/** Builds the session replay pipeline for a deployment. */
export type SessionReplayPipelineFactory = (config: SessionReplayPipelineConfig) => SessionReplayPipeline

/** Runs each poll batch through the session replay pipeline in one stage, so batches never overlap. */
export class SessionReplayPipelineRunner implements StagedBatchRunner {
    public readonly stages = ['ingest'] as const
    private pipeline!: SessionReplayPipeline

    constructor(
        private readonly createPipeline: SessionReplayPipelineFactory,
        private readonly scheduler: PromiseScheduler
    ) {}

    public start(config: SessionReplayPipelineConfig): void {
        this.pipeline = this.createPipeline(config)
    }

    public run(messages: Message[], batch: AdmittedBatch<void>, committer: BatchCommitter): Promise<void> {
        return batch
            .stage('ingest', () =>
                committer.commit((recorder) =>
                    runSessionReplayPipeline(this.pipeline, messages, recorder, this.scheduler)
                )
            )
            .done()
    }
}
