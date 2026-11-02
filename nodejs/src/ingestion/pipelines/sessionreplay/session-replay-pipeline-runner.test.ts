import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'

import { BatchStages } from './batch-stages'
import { SessionReplayPipeline, SessionReplayPipelineConfig } from './session-replay-pipeline'
import { SessionReplayPipelineRunner } from './session-replay-pipeline-runner'
import { BatchCommitter } from './staged-batch'

describe('SessionReplayPipelineRunner', () => {
    it.each([
        ['one commit when the limit is off', 0, 1],
        ['one commit for a poll under the limit', 100, 1],
        ['one commit for each part of a poll past the limit', 15, 2],
    ])('makes %s', async (_, maxDecodedBytesPerWrite, commits) => {
        const runner = new SessionReplayPipelineRunner(() => ({}) as SessionReplayPipeline, new PromiseScheduler())
        runner.start({ maxDecodedBytesPerWrite } as SessionReplayPipelineConfig)
        const committer: BatchCommitter = {
            knownRetention: () => undefined,
            commit: jest.fn().mockResolvedValue(undefined),
        }
        const messages = [{ value: Buffer.alloc(10) }, { value: Buffer.alloc(10) }] as Message[]

        await runner.run(messages, new BatchStages(runner.stages).admit(), committer)

        expect(committer.commit).toHaveBeenCalledTimes(commits)
    })
})
