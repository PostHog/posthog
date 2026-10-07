import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'

import type { RecordingsQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AccessControlResourceType, type SessionRecordingType } from '~/types'

import { accountSessionReplaysLogic, type AccountSessionReplaysLogicProps } from './accountSessionReplaysLogic'
import { getAccountReplayRecordings } from './accountSessionReplaysQuery'
import { AccountsEvents } from './constants'

jest.mock('./accountSessionReplaysQuery', () => ({
    ...jest.requireActual('./accountSessionReplaysQuery'),
    getAccountReplayRecordings: jest.fn(),
}))
jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    userHasAccess: jest.fn(),
}))

const mockList = jest.mocked(getAccountReplayRecordings)
const mockAccess = jest.mocked(userHasAccess)
const PERSON_UUID = '11111111-2222-4333-8444-555555555555'
const createRecording = (id: string): SessionRecordingType => ({
    id,
    viewed: false,
    viewers: [],
    recording_duration: 60,
    start_time: '2026-06-01T10:00:00Z',
    end_time: '2026-06-01T10:01:00Z',
    snapshot_source: 'web',
    person: { id: '42', uuid: PERSON_UUID, name: 'Example user', distinct_ids: ['example-user'], properties: {} },
})
const createResponse = (ids: string[], hasNext = false, cursor?: string): RecordingsQueryResponse => ({
    results: ids.map(createRecording),
    has_next: hasNext,
    next_cursor: cursor,
})
const DEFAULT_PROPS: AccountSessionReplaysLogicProps = {
    projectId: MOCK_DEFAULT_TEAM.id,
    accountId: 'account-one',
    externalId: 'account-key-one',
    instanceId: 'tile-one',
}

function createDeferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (error: Error) => void } {
    let resolve!: (value: T) => void
    let reject!: (error: Error) => void
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise
        reject = rejectPromise
    })
    return { promise, resolve, reject }
}

describe('accountSessionReplaysLogic', () => {
    const mounted: ReturnType<typeof accountSessionReplaysLogic>[] = []

    beforeEach(() => {
        jest.clearAllMocks()
        mockList.mockReset()
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: { ...MOCK_DEFAULT_TEAM.customer_analytics_config, account_group_type_index: 0 },
        })
        mockAccess.mockReturnValue(true)
        mockList.mockResolvedValue(createResponse(['recording-one'], true, 'cursor-one'))
    })

    afterEach(() => {
        mounted.splice(0).forEach((logic) => logic.unmount())
        jest.restoreAllMocks()
    })

    const mount = (
        props: Partial<AccountSessionReplaysLogicProps> = {}
    ): ReturnType<typeof accountSessionReplaysLogic> => {
        const logic = accountSessionReplaysLogic({ ...DEFAULT_PROPS, ...props })
        logic.mount()
        mounted.push(logic)
        return logic
    }

    it.each([
        { dateFrom: '-14d', requestFrom: '-14d' },
        { dateFrom: null, requestFrom: 'all' },
    ])(
        'ignores restored identity, filters, and user selection, preserving only dates: %p',
        async ({ dateFrom, requestFrom }) => {
            const logic = mount({
                initialConfig: {
                    externalId: 'another-account',
                    properties: [],
                    person_uuid: PERSON_UUID,
                    dateRange: { date_from: dateFrom, date_to: null },
                },
            })
            await expectLogic(logic).toFinishAllListeners()
            expect(mockList).toHaveBeenLastCalledWith(
                MOCK_DEFAULT_TEAM.id,
                expect.objectContaining({
                    properties: [{ key: '$group_0', type: 'event', operator: 'exact', value: ['account-key-one'] }],
                    date_from: requestFrom,
                    date_to: null,
                    person_uuid: undefined,
                    limit: 20,
                    order: 'start_time',
                    order_direction: 'DESC',
                    event_match_scope: 'session',
                })
            )
            expect(mockList.mock.calls.at(-1)?.[1]).not.toHaveProperty('offset')
            expect(mockList.mock.calls.at(-1)?.[1]).not.toHaveProperty('after')
            expect(logic.values.selectedUser).toBeNull()
        }
    )

    it('does not request recordings when the group mapping is missing, even if tile config supplies one', async () => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: {
                ...MOCK_DEFAULT_TEAM.customer_analytics_config,
                account_group_type_index: null,
            },
        })
        const logic = mount({ initialConfig: { group_type_index: 0 } })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.replayList?.status).toBe('setup')
        expect(mockList).not.toHaveBeenCalled()
    })

    it.each([AccessControlResourceType.CustomerAnalytics, AccessControlResourceType.SessionRecording])(
        'does not request recordings when access is denied to %s',
        async (resource) => {
            mockAccess.mockImplementation((requestedResource) => requestedResource !== resource)
            const logic = mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.replayList?.status).toBe('denied')
            expect(mockList).not.toHaveBeenCalled()
        }
    )

    it('appends without duplicate rows, guards repeat clicks, and stops at the final page', async () => {
        const logic = mount()
        await expectLogic(logic).toFinishAllListeners()
        const page = createDeferred<RecordingsQueryResponse>()
        mockList.mockReturnValueOnce(page.promise)
        logic.actions.loadMore()
        logic.actions.loadMore()
        expect(mockList).toHaveBeenCalledTimes(2)
        expect(mockList).toHaveBeenLastCalledWith(
            MOCK_DEFAULT_TEAM.id,
            expect.objectContaining({ after: 'cursor-one' })
        )
        page.resolve(createResponse(['recording-one', 'recording-two']))
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.replayList?.recordings.map(({ id }) => id)).toEqual(['recording-one', 'recording-two'])
        expect(logic.values.replayList?.hasMore).toBe(false)
        logic.actions.loadMore()
        expect(mockList).toHaveBeenCalledTimes(2)
    })

    it('uses raw page progress for offset fallback rather than the deduplicated row count', async () => {
        mockList.mockResolvedValueOnce(createResponse(['recording-one', 'recording-two'], true))
        const logic = mount()
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockResolvedValueOnce(createResponse(['recording-two', 'recording-three'], true))
        logic.actions.loadMore()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadMore()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenLastCalledWith(MOCK_DEFAULT_TEAM.id, expect.objectContaining({ offset: 4 }))
    })

    it.each([
        { scope: 'tile', props: { instanceId: 'tile-two' }, externalId: 'account-key-one' },
        {
            scope: 'account',
            props: { accountId: 'account-two', externalId: 'account-key-two' },
            externalId: 'account-key-two',
        },
    ])('keeps $scope state separate and saves dates without the temporary user', async ({ props, externalId }) => {
        const onConfigChange = jest.fn()
        const first = mount({ onConfigChange })
        const second = mount({
            ...props,
            initialConfig: { dateRange: { date_from: '-30d', date_to: null } },
        })
        await expectLogic(first).toFinishAllListeners()
        await expectLogic(second).toFinishAllListeners()
        const secondList = second.values.replayList
        expect(mockList).toHaveBeenLastCalledWith(
            MOCK_DEFAULT_TEAM.id,
            expect.objectContaining({
                properties: [{ key: '$group_0', type: 'event', operator: 'exact', value: [externalId] }],
                person_uuid: undefined,
            })
        )
        first.actions.setUser(first.values.availableUsers[0])
        await expectLogic(first).toFinishAllListeners()
        expect(mockList).toHaveBeenLastCalledWith(
            MOCK_DEFAULT_TEAM.id,
            expect.objectContaining({ person_uuid: PERSON_UUID })
        )
        expect(mockList.mock.calls.at(-1)?.[1]).not.toHaveProperty('offset')
        expect(mockList.mock.calls.at(-1)?.[1]).not.toHaveProperty('after')
        expect(onConfigChange).not.toHaveBeenCalled()
        first.actions.setDateRange('-14d', null)
        await expectLogic(first).toFinishAllListeners()
        expect(onConfigChange).toHaveBeenLastCalledWith({ dateRange: { date_from: '-14d', date_to: null } })
        expect(second.values.dateRange.date_from).toBe('-30d')
        expect(second.values.selectedUser).toBeNull()
        expect(second.values.replayList).toBe(secondList)
    })

    it.each(['success', 'denied'])('discards an older filter %s after the new filter resolves', async (outcome) => {
        const oldPage = createDeferred<RecordingsQueryResponse>()
        mockList.mockReturnValueOnce(oldPage.promise)
        const logic = mount()
        logic.actions.setDateRange('-30d', null)
        await waitFor(() => expect(logic.values.replayList?.status).toBe('ready'))
        if (outcome === 'success') {
            oldPage.resolve(createResponse(['stale-recording']))
        } else {
            oldPage.reject(new ApiError('Access denied', 403))
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.replayList?.status).toBe('ready')
        expect(logic.values.replayList?.recordings.map(({ id }) => id)).toEqual(['recording-one'])
    })

    it.each([401, 403, 500])('distinguishes denied requests from retryable errors: %s', async (status) => {
        mockList.mockRejectedValueOnce(new ApiError('Request failed', status))
        const logic = mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.replayList?.status).toBe(status === 500 ? 'error' : 'denied')
        logic.actions.retry()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.replayList?.status).toBe('ready')
    })

    it('retries a failed next page without clearing already loaded rows', async () => {
        const logic = mount()
        await expectLogic(logic).toFinishAllListeners()
        mockList.mockRejectedValueOnce(new ApiError('Request failed', 500))
        logic.actions.loadMore()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.replayList?.recordings.map(({ id }) => id)).toEqual(['recording-one'])
        expect(logic.values.replayList?.status).toBe('error')
        mockList.mockResolvedValueOnce(createResponse(['recording-two']))
        logic.actions.retry()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockList).toHaveBeenLastCalledWith(
            MOCK_DEFAULT_TEAM.id,
            expect.objectContaining({ after: 'cursor-one' })
        )
        expect(logic.values.replayList?.recordings.map(({ id }) => id)).toEqual(['recording-one', 'recording-two'])
    })

    it('opens the global player without changing filters or rows and emits no customer data', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        sessionPlayerModalLogic.mount()
        try {
            const logic = mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setUser(logic.values.availableUsers[0])
            await expectLogic(logic).toFinishAllListeners()
            const list = logic.values.replayList
            logic.actions.openRecording('recording-one')
            expect(sessionPlayerModalLogic.values.activeSessionRecording).toEqual({ id: 'recording-one' })
            sessionPlayerModalLogic.actions.closeSessionPlayer()
            expect(logic.values.replayList).toBe(list)
            expect(logic.values.selectedUser?.value).toBe(PERSON_UUID)
            expect(capture).toHaveBeenCalledWith(AccountsEvents.ReplaysRecordingOpened)
            const replayCalls = capture.mock.calls.filter(([event]) =>
                event.startsWith('customer analytics account replay')
            )
            expect(JSON.stringify(replayCalls)).not.toMatch(
                /account-key-one|recording-one|Example user|example-user|11111111/
            )
        } finally {
            sessionPlayerModalLogic.unmount()
        }
    })
})
