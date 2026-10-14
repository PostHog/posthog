import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { userHasAccess } from 'lib/utils/accessControlUtils'

import { initKeaTests } from '~/test/init'
import type { SessionRecordingType } from '~/types'

import { AccountSessionReplays } from './AccountSessionReplays'
import { getAccountReplayRecordings } from './accountSessionReplaysQuery'

jest.mock('./accountSessionReplaysQuery', () => ({
    ...jest.requireActual('./accountSessionReplaysQuery'),
    getAccountReplayRecordings: jest.fn(),
}))
jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    userHasAccess: jest.fn(),
}))

const PERSON_UUID = '11111111-2222-4333-8444-555555555555'
const recording: SessionRecordingType = {
    id: '019781d7-0000-7000-8000-000000000001',
    viewed: false,
    viewers: [],
    recording_duration: 60,
    start_time: '2026-06-01T10:00:00Z',
    end_time: '2026-06-01T10:01:00Z',
    snapshot_source: 'web',
    person: {
        id: '42',
        uuid: PERSON_UUID,
        name: 'example-user@example.com',
        distinct_ids: ['example-user'],
        properties: {},
    },
}

const mockList = jest.mocked(getAccountReplayRecordings)

describe('AccountSessionReplays', () => {
    beforeEach(() => {
        initKeaTests(true, {
            ...MOCK_DEFAULT_TEAM,
            customer_analytics_config: { ...MOCK_DEFAULT_TEAM.customer_analytics_config, account_group_type_index: 0 },
        })
        jest.mocked(userHasAccess).mockReturnValue(true)
        mockList.mockReset()
        mockList.mockResolvedValue({ results: [recording], has_next: false })
    })

    afterEach(cleanup)

    it('excludes user option labels from autocapture without blocking selection', async () => {
        render(<AccountSessionReplays accountId="example-account" externalId="example-account-key" />)
        await screen.findByLabelText('Open recording')
        fireEvent.click(screen.getByLabelText('Filter recordings by user'))
        const option = await screen.findByText('example-user@example.com')
        expect(option.closest('.ph-no-capture')).not.toBeNull()
        fireEvent.click(option)
        await waitFor(() =>
            expect(mockList).toHaveBeenLastCalledWith(
                MOCK_DEFAULT_TEAM.id,
                expect.objectContaining({ person_uuid: PERSON_UUID })
            )
        )
    })

    it('keeps every paged row in the scrollport with filters, description, and Load more outside', async () => {
        const names = Array.from({ length: 12 }, (_, index) => `example-user-${index + 1}`)
        const loadedRecordings = names.map((distinctId, index) => ({
            ...recording,
            id: `example-loaded-recording-${index}`,
            person: { ...recording.person!, distinct_ids: [distinctId] },
        }))
        mockList.mockResolvedValue({
            results: loadedRecordings.slice(0, 11),
            has_next: true,
            next_cursor: 'example-cursor',
        })
        const { container } = render(
            <AccountSessionReplays accountId="example-account" externalId="example-account-key" />
        )
        await screen.findByText('example-user-11')
        const scrollport = container.querySelector('[data-attr="account-replays-list"]')
        const getRowNames = (): (string | null)[] =>
            Array.from(
                scrollport?.querySelectorAll<HTMLButtonElement>('button[data-attr="account-replays-open-recording"]') ??
                    []
            ).map((row) => within(row).getByText(/^example-user-\d+$/).textContent)
        expect(getRowNames()).toEqual(names.slice(0, 11))
        const dateFilter = container.querySelector('[data-attr="date-filter"]')
        expect(dateFilter).not.toBeNull()
        expect(dateFilter?.closest('[data-attr="account-replays-list"]')).toBeNull()
        expect(
            screen.getByLabelText('Filter recordings by user').closest('[data-attr="account-replays-list"]')
        ).toBeNull()
        expect(
            screen
                .getByText(/Recordings include activity for this account/)
                .closest('[data-attr="account-replays-list"]')
        ).toBeNull()
        expect(screen.getByText('Load more').closest('[data-attr="account-replays-list"]')).toBeNull()
        mockList.mockResolvedValueOnce({ results: loadedRecordings.slice(11), has_next: false })
        fireEvent.click(screen.getByText('Load more'))
        await waitFor(() => expect(getRowNames()).toEqual(names))
        expect(screen.queryByText('Load more')).toBeNull()
    })
})
