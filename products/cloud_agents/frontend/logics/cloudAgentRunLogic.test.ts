import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { cloudAgentsRunsEventsRetrieve, cloudAgentsRunsMessagesCreate, cloudAgentsRunsRetrieve } from '../generated/api'
import type { CloudAgentRunApi, CloudAgentRunStatusEnumApi } from '../generated/api.schemas'
import { RUN_POLL_INTERVAL_MS, cloudAgentRunLogic } from './cloudAgentRunLogic'

jest.mock('../generated/api')

const retrieveRun = jest.mocked(cloudAgentsRunsRetrieve)
const retrieveEvents = jest.mocked(cloudAgentsRunsEventsRetrieve)
const createMessage = jest.mocked(cloudAgentsRunsMessagesCreate)

const runWithStatus = (status: CloudAgentRunStatusEnumApi): CloudAgentRunApi =>
    ({ id: 'run-1', status, prompt: 'Fix the test' }) as CloudAgentRunApi

describe('cloudAgentRunLogic', () => {
    let logic: ReturnType<typeof cloudAgentRunLogic.build>

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        retrieveEvents.mockResolvedValue({ events: [], truncated: false })
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.resetAllMocks()
    })

    test.each([
        ['queued', 'idle', 2],
        ['running', 'idle', 2],
        ['running', 'done', 2],
        ['idle', 'idle', 1],
        ['done', 'done', 1],
    ] as const)(
        'a run that loads as %s and then reads as %s is read %i time(s) in total',
        async (firstStatus, laterStatus, expectedReads) => {
            retrieveRun.mockResolvedValueOnce(runWithStatus(firstStatus)).mockResolvedValue(runWithStatus(laterStatus))

            logic = cloudAgentRunLogic({ id: 'run-1' })
            logic.mount()
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.run?.status).toEqual(firstStatus)

            await jest.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS * 5)

            expect(logic.values.run?.status).toEqual(laterStatus)
            expect(retrieveRun).toHaveBeenCalledTimes(expectedReads)
        }
    )

    test.each([
        ['credential_owner_required', 403, null, 'only that person can continue it'],
        ['run_stopping', 409, null, 'Wait until it stops'],
        ['usage_limited', 429, null, 'reached its usage limit'],
        ['concurrency_limited', 429, null, 'maximum number of runs in progress'],
        ['run_not_resumable', 409, null, 'cannot be continued'],
        ['run_done', 409, null, 'Start a new run to continue the work'],
        ['some_new_code', 400, 'The message is too long.', 'The message is too long.'],
        [null, 500, null, 'Could not send the message. Try again in a moment.'],
    ])(
        'a follow-up that fails with code %p shows a message that says what to do',
        async (code, status, detail, expected) => {
            retrieveRun.mockResolvedValue(runWithStatus('idle'))
            createMessage.mockRejectedValue(new ApiError(undefined, status, undefined, { code, detail }))

            logic = cloudAgentRunLogic({ id: 'run-1' })
            logic.mount()
            await jest.advanceTimersByTimeAsync(0)
            logic.actions.setFollowupText('Also update the changelog')
            logic.actions.sendFollowup()
            await jest.advanceTimersByTimeAsync(0)

            expect(logic.values).toMatchObject({
                followupError: expect.stringContaining(expected),
                followupSending: false,
                followupText: 'Also update the changelog',
            })
        }
    )

    it('reads the run again when a follow-up shows that the run is done', async () => {
        retrieveRun.mockResolvedValueOnce(runWithStatus('idle')).mockResolvedValue(runWithStatus('done'))
        createMessage.mockRejectedValue(new ApiError(undefined, 409, undefined, { code: 'run_done', detail: null }))

        logic = cloudAgentRunLogic({ id: 'run-1' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values).toMatchObject({ isDone: false, isActive: false })

        logic.actions.setFollowupText('Also update the changelog')
        logic.actions.sendFollowup()
        await jest.advanceTimersByTimeAsync(0)

        expect(retrieveRun).toHaveBeenCalledTimes(2)
        expect(logic.values).toMatchObject({ isDone: true, isActive: false })
    })

    it('resumes the poll when a follow-up puts a stopped run back in the queue', async () => {
        retrieveRun.mockResolvedValue(runWithStatus('idle'))
        createMessage.mockResolvedValue({ resumed: true, run: runWithStatus('queued') })

        logic = cloudAgentRunLogic({ id: 'run-1' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS * 2)
        expect(retrieveRun).toHaveBeenCalledTimes(1)

        logic.actions.setFollowupText('Also update the changelog')
        logic.actions.sendFollowup()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values).toMatchObject({ followupText: '', followupError: null, isActive: true })

        await jest.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS)
        expect(retrieveRun).toHaveBeenCalledTimes(2)
    })
})
