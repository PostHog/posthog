import { Message } from 'node-rdkafka'

import { AdmittedBatch } from './batch-stages'
import { SessionReplayBatchProgress, SessionReplayPipelineConfig } from './session-replay-pipeline'
import { SessionBatchRecorder } from './sessions/session-batch-recorder'
import { RetentionPeriod } from './shared/constants'

/** Tells whether this pod still holds a partition. A batch that is still in flight after a revoke then writes nothing that the new owner will replay. */
export type PartitionOwnership = (partition: number) => boolean

/** How a runner reaches the recorder of the ingester. The write runs under the batch lock and reports the progress of the batch for the partitions that the pod holds. The ingester tracks those offsets and decides whether to flush. Only the write receives the recorder, because a flush can replace the recorder at any time. */
export interface BatchCommitter {
    /** The retention that is already resolved for a session in the current batch, or undefined. The current batch is the batch at the time of the call. */
    knownRetention(teamId: number, sessionId: string): RetentionPeriod | undefined
    commit(
        write: (recorder: SessionBatchRecorder, isAssigned: PartitionOwnership) => Promise<SessionReplayBatchProgress>
    ): Promise<void>
}

/** Does the work of each stage for one poll batch. The ingester sizes its consumer from the stages before the runner starts. It admits each batch to the stages in poll order and gives the runner a committer to write through. */
export interface StagedBatchRunner {
    readonly stages: readonly string[]
    start(config: SessionReplayPipelineConfig): void
    /** Resolves when the batch is written and its offsets are tracked. */
    run(messages: Message[], batch: AdmittedBatch<void>, committer: BatchCommitter): Promise<void>
}

/** A staged batch is done when its last stage completes. That stage can wait behind every earlier batch in flight and behind a flush, so this timeout is longer than the consumer default for a short background task. It stays below the max.poll.interval.ms of librdkafka (5 minutes). At the lookahead the consumer waits on the oldest batch, and the broker removes a member that waits longer than that interval before this timeout can fire. */
export const STAGED_BATCH_TIMEOUT_MS = 4 * 60 * 1000

/** A revoke drains every batch in flight before the revoke hook flushes. The last stages of those batches run one after another. The drain needs the lookahead multiplied by the slowest stage, plus the flush of the hook, all below the 5-minute max.poll.interval.ms of librdkafka. */
export const STAGED_BATCH_REBALANCE_TIMEOUT_MS = 3 * 60 * 1000
