import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { ok } from '~/ingestion/framework/results'
import { SessionReplayBatchProgress } from '~/ingestion/pipelines/sessionreplay'
import { BatchStages } from '~/ingestion/pipelines/sessionreplay/batch-stages'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { BatchCommitter } from '~/ingestion/pipelines/sessionreplay/staged-batch'
import {
    buildMlMirrorStagedRunner,
    mlMirrorTestMessage,
    mlMirrorTestPipelineConfig,
    mlMirrorTestServices,
    parseTestHeaders,
    scrubbedTestMessage,
} from '~/tests/helpers/ml-mirror-staged-batch'

import { createParseAndAnonymizeMessageStep } from './parse-and-anonymize-step'
import { ML_BATCH_STAGES, MlMirrorStagedBatchRunner } from './staged-batch-runner'

jest.mock('~/ingestion/common/steps/event-preprocessing', () => ({
    createParseHeadersStep: jest.fn(),
    createApplyEventRestrictionsStep: jest.fn(),
}))
jest.mock('./parse-and-anonymize-step', () => ({
    createParseAndAnonymizeMessageStep: jest.fn(),
}))

const mockCreateParseHeadersStep = createParseHeadersStep as jest.Mock
const mockCreateApplyEventRestrictionsStep = createApplyEventRestrictionsStep as jest.Mock
const mockCreateParseAndAnonymizeMessageStep = createParseAndAnonymizeMessageStep as jest.Mock

describe('ml-mirror staged batch runner', () => {
    const SESSION_A = '01a0a4f0-3200-7000-8000-000000000001'
    const SESSION_B = '01a0a4f0-3200-7000-8000-000000000002'
    const OPTED_IN_TOKEN = 'opted-in'
    const OPTED_OUT_TOKEN = 'opted-out'
    const now = DateTime.now()
    const services = mlMirrorTestServices((token) => token === OPTED_IN_TOKEN)

    let promiseScheduler: PromiseScheduler
    let stages: BatchStages
    // Per `${sessionId}:${offset}`: a promise the mocked scrub awaits before completing.
    let scrubGates: Map<string, Promise<void>>
    let scrubStarts: Set<string>

    beforeEach(() => {
        jest.clearAllMocks()
        promiseScheduler = new PromiseScheduler()
        stages = new BatchStages(ML_BATCH_STAGES)
        scrubGates = new Map()
        scrubStarts = new Set()

        mockCreateParseHeadersStep.mockReturnValue(parseTestHeaders)
        mockCreateApplyEventRestrictionsStep.mockReturnValue((input: unknown) => Promise.resolve(ok(input)))
        mockCreateParseAndAnonymizeMessageStep.mockReturnValue(
            async (input: { message: Message; headers: Record<string, string> }) => {
                const scrubKey = `${input.headers.session_id}:${input.message.offset}`
                scrubStarts.add(scrubKey)
                await (scrubGates.get(scrubKey) ?? Promise.resolve())
                return ok({ ...input, parsedMessage: scrubbedTestMessage(input, now) })
            }
        )
    })

    function buildRunner(): MlMirrorStagedBatchRunner {
        return buildMlMirrorStagedRunner(mlMirrorTestPipelineConfig(promiseScheduler, services), {
            anonymizeMaxConcurrency: 2,
        })
    }

    function message(sessionId: string, offset: number, token = OPTED_IN_TOKEN): Message {
        return mlMirrorTestMessage(sessionId, offset, token)
    }

    function recorder(): jest.Mocked<SessionBatchRecorder> {
        return {
            record: jest.fn().mockResolvedValue(undefined),
            getRetention: jest.fn().mockReturnValue(undefined),
        } as unknown as jest.Mocked<SessionBatchRecorder>
    }

    function gate(key: string): () => void {
        let release!: () => void
        scrubGates.set(key, new Promise<void>((resolve) => (release = resolve)))
        return release
    }

    async function until(condition: () => boolean): Promise<void> {
        for (let i = 0; i < 5000 && !condition(); i++) {
            await new Promise(setImmediate)
        }
        if (!condition()) {
            throw new Error('condition not reached while a scrub gate was held')
        }
    }

    it('prepares the next batch while the current one scrubs, and scrubs it only once the current one is done', async () => {
        const releaseA = gate(`${SESSION_A}:1`)
        const releaseB = gate(`${SESSION_B}:2`)
        const runner = buildRunner()
        const committed: number[] = []
        const committer: BatchCommitter = {
            knownRetention: () => undefined,
            commit: async (write) => {
                committed.push(...(await write(recorder(), () => true)).okMessages.map((m) => m.offset))
            },
        }

        const first = runner.run([message(SESSION_A, 1)], stages.admit(), committer)
        const second = runner.run([message(SESSION_B, 2)], stages.admit(), committer)
        try {
            await until(() => scrubStarts.has(`${SESSION_A}:1`))
            // The second batch's prepare stage ran to its end (the seen-mark is its last step) while the first batch's scrub was still held.
            await until(() => (services.sessionTracker.markSeen as jest.Mock).mock.calls.length === 2)
            expect(scrubStarts.has(`${SESSION_B}:2`)).toBe(false)
            releaseA()
            await until(() => scrubStarts.has(`${SESSION_B}:2`))
        } finally {
            releaseA()
            releaseB()
        }
        await Promise.all([first, second])

        expect(committed).toEqual([1, 2])
    })

    it('records into the recorder current at commit time, not the one current at feed time', async () => {
        const releaseA = gate(`${SESSION_A}:1`)
        const runner = buildRunner()
        const fedWith = recorder()
        const flushedInto = recorder()
        let current = fedWith
        const committer: BatchCommitter = {
            knownRetention: (teamId, sessionId) => current.getRetention(teamId, sessionId),
            commit: async (write) => {
                await write(current, () => true)
            },
        }

        const run = runner.run([message(SESSION_A, 1)], stages.admit(), committer)
        try {
            await until(() => scrubStarts.has(`${SESSION_A}:1`))
            current = flushedInto
        } finally {
            releaseA()
        }
        await run

        expect(fedWith.record).not.toHaveBeenCalled()
        expect(flushedInto.record).toHaveBeenCalledTimes(1)
    })

    it('advances the offset past dropped messages but reports only recorded ones as recorded', async () => {
        const runner = buildRunner()
        let maxOffsets: Map<number, number> | undefined
        let recorded: number[] = []
        const committer: BatchCommitter = {
            knownRetention: () => undefined,
            commit: async (write) => {
                const progress = await write(recorder(), () => true)
                recorded = progress.okMessages.map((m) => m.offset)
                maxOffsets = progress.maxOffsets
            },
        }

        await runner.run([message(SESSION_A, 5, OPTED_OUT_TOKEN), message(SESSION_B, 6)], stages.admit(), committer)

        expect(maxOffsets?.get(0)).toBe(6)
        expect(recorded).toEqual([6])
    })

    it('commits an empty poll batch so the ingester can still flush on age', async () => {
        const runner = buildRunner()
        let progress: SessionReplayBatchProgress | undefined
        const commit = jest.fn().mockImplementation(async (write) => {
            progress = await write(recorder(), () => true)
        })

        await runner.run([], stages.admit(), { knownRetention: () => undefined, commit })

        expect(commit).toHaveBeenCalledTimes(1)
        expect(progress?.maxOffsets).toEqual(new Map())
    })

    it('records nothing for partitions the pod no longer holds at commit time', async () => {
        const runner = buildRunner()
        const held = recorder()
        let recorded: Message[] = []
        let maxOffsets: Map<number, number> | undefined
        const committer: BatchCommitter = {
            knownRetention: () => undefined,
            commit: async (write) => {
                const progress = await write(held, () => false)
                recorded = progress.okMessages
                maxOffsets = progress.maxOffsets
            },
        }

        await runner.run([message(SESSION_A, 1)], stages.admit(), committer)

        expect(held.record).not.toHaveBeenCalled()
        expect(recorded).toEqual([])
        expect(maxOffsets?.size).toBe(0)
    })

    it('still tracks offsets for a batch that drops every message', async () => {
        const runner = buildRunner()
        let maxOffsets: Map<number, number> | undefined
        let recorded: Message[] = []
        const committer: BatchCommitter = {
            knownRetention: () => undefined,
            commit: async (write) => {
                const progress = await write(recorder(), () => true)
                recorded = progress.okMessages
                maxOffsets = progress.maxOffsets
            },
        }

        await runner.run([message(SESSION_A, 7, OPTED_OUT_TOKEN)], stages.admit(), committer)

        expect(maxOffsets?.get(0)).toBe(7)
        expect(recorded).toEqual([])
        expect(scrubStarts.size).toBe(0)
    })
})
