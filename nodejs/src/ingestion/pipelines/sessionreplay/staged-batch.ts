import { Message } from 'node-rdkafka'

import { AdmittedBatch } from './batch-stages'
import { SessionReplayPipelineConfig } from './session-replay-pipeline'
import { SessionBatchRecorder } from './sessions/session-batch-recorder'
import { RetentionPeriod } from './shared/constants'

/** Answers whether this pod still holds a partition, so a batch that outlives a revoke records nothing the new owner will replay. */
export type PartitionOwnership = (partition: number) => boolean

/** How a staged runner reaches the ingester's recorder: it records under the batch lock, hands back the messages it recorded, and leaves the flush decision to the ingester. The recorder itself is only ever handed to the record callback, because a flush replaces it at any time. */
export interface BatchCommitter {
    /** The retention already resolved for a session held in the batch current at the time of the call, if any. */
    knownRetention(teamId: number, sessionId: string): RetentionPeriod | undefined
    commit(
        maxOffsets: Map<number, number>,
        record: (recorder: SessionBatchRecorder, isAssigned?: PartitionOwnership) => Promise<Message[]>
    ): Promise<void>
}

/** Does the work of each stage for one poll batch. The ingester sizes its consumer from the stages before the runner starts, admits each batch to them in poll order, and hands the runner the committer to record through. */
export interface StagedBatchRunner {
    readonly stages: readonly string[]
    start(config: SessionReplayPipelineConfig): void
    /** Resolves once the batch is recorded and its offsets tracked. */
    run(messages: Message[], batch: AdmittedBatch<void>, committer: BatchCommitter): Promise<void>
}

/** A staged batch is done once its last stage has run, which can sit behind every earlier batch still in flight and a flush, so this is longer than the consumer's default for a quick background task. It stays under librdkafka's max.poll.interval.ms (5 minutes): at the lookahead the consumer waits on the oldest batch, and a member that waits longer than that is fenced before this timeout could fire. */
export const STAGED_BATCH_TIMEOUT_MS = 4 * 60 * 1000

/** A revoke drains every batch in flight before the revoke hook flushes. The last stages of those batches run one after another, so the drain needs the lookahead times the slowest stage plus the hook's own flush, all under librdkafka's 5-minute max.poll.interval.ms. */
export const STAGED_BATCH_REBALANCE_TIMEOUT_MS = 3 * 60 * 1000
