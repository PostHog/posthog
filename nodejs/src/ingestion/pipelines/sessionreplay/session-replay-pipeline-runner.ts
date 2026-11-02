import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import {
    SessionReplayPipeline,
    SessionReplayPipelineConfig,
    runSessionReplayPipeline,
} from '~/ingestion/pipelines/sessionreplay'

import { AdmittedBatch } from './batch-stages'
import { splitByDecodedBytes } from './parse-message-step'
import { BatchCommitter, StagedBatchRunner } from './staged-batch'

/** Builds the session replay pipeline for a deployment. */
export type SessionReplayPipelineFactory = (config: SessionReplayPipelineConfig) => SessionReplayPipeline

/** Runs each poll batch through the session replay pipeline in one stage, so batches never overlap. */
export class SessionReplayPipelineRunner implements StagedBatchRunner {
    public readonly stages = ['ingest'] as const
    private pipeline!: SessionReplayPipeline
    private maxDecodedBytesPerWrite = 0

    constructor(
        private readonly createPipeline: SessionReplayPipelineFactory,
        private readonly scheduler: PromiseScheduler
    ) {}

    public start(config: SessionReplayPipelineConfig): void {
        this.pipeline = this.createPipeline(config)
        this.maxDecodedBytesPerWrite = config.maxDecodedBytesPerWrite ?? 0
    }

    public run(messages: Message[], batch: AdmittedBatch<void>, committer: BatchCommitter): Promise<void> {
        return batch
            .stage('ingest', async () => {
                for (const part of splitByDecodedBytes(messages, this.maxDecodedBytesPerWrite)) {
                    await committer.commit((recorder) =>
                        runSessionReplayPipeline(this.pipeline, part, recorder, this.scheduler)
                    )
                }
            })
            .done()
    }
}
