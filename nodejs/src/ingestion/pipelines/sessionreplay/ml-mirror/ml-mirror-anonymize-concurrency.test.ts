import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { ok } from '~/ingestion/framework/results'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import {
    buildMlMirrorStagedRunner,
    mlMirrorTestMessage,
    mlMirrorTestPipelineConfig,
    mlMirrorTestServices,
    parseTestHeaders,
    runMlMirrorBatch,
    scrubbedTestMessage,
} from '~/tests/helpers/ml-mirror-staged-batch'

import { createParseAndAnonymizeMessageStep } from './parse-and-anonymize-step'
import { MlMirrorStagedBatchRunner } from './staged-batch-runner'

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

describe('ml-mirror anonymize concurrency', () => {
    const SESSION_A = '01a0a4f0-3200-7000-8000-000000000001'
    const SESSION_B = '01a0a4f0-3200-7000-8000-000000000002'
    const now = DateTime.now()
    const services = mlMirrorTestServices()

    let recordMock: jest.Mock
    let promiseScheduler: PromiseScheduler
    // Per `${sessionId}:${offset}`: a promise the mocked scrub awaits before completing.
    let scrubGates: Map<string, Promise<void>>
    let scrubStarts: Set<string>

    beforeEach(() => {
        jest.clearAllMocks()
        recordMock = jest.fn().mockResolvedValue(undefined)
        promiseScheduler = new PromiseScheduler()
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

    const message = mlMirrorTestMessage

    function recordedOffsets(sessionId: string): number[] {
        return recordMock.mock.calls
            .filter((call) => call[0].message.session_id === sessionId)
            .map((call) => call[0].message.metadata.offset)
    }

    async function until(condition: () => boolean): Promise<void> {
        for (let i = 0; i < 5000 && !condition(); i++) {
            await new Promise(setImmediate)
        }
        if (!condition()) {
            throw new Error('condition not reached while a scrub gate was held')
        }
    }

    it('scrubs messages concurrently, including messages of the same session', async () => {
        let releaseFirstScrub!: () => void
        let releaseSecondScrub!: () => void
        scrubGates.set(`${SESSION_A}:1`, new Promise<void>((resolve) => (releaseFirstScrub = resolve)))
        scrubGates.set(`${SESSION_A}:2`, new Promise<void>((resolve) => (releaseSecondScrub = resolve)))

        const recorder = {
            record: recordMock,
            getRetention: jest.fn().mockReturnValue(undefined),
        } as unknown as SessionBatchRecorder
        const run = runMlMirrorBatch(
            buildRunner(),
            [message(SESSION_A, 1), message(SESSION_A, 2), message(SESSION_B, 3)],
            recorder
        )

        try {
            // Both of sess-a's scrubs are in flight at once — sequential processing never starts
            // the second scrub while the first is gated, and per-session grouping never starts a
            // session's second message while its first is gated.
            await until(() => scrubStarts.has(`${SESSION_A}:1`) && scrubStarts.has(`${SESSION_A}:2`))
        } finally {
            releaseFirstScrub()
            releaseSecondScrub()
        }
        await run

        // No ordering guarantees, so only membership is asserted.
        expect(recordedOffsets(SESSION_A).sort()).toEqual([1, 2])
        expect(recordedOffsets(SESSION_B)).toEqual([3])
    })
})
