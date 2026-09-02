import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { announcementsLogic } from './announcementsLogic'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))
const mockPerformQuery = performQuery as jest.Mock

describe('announcementsLogic', () => {
    let logic: ReturnType<typeof announcementsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/announcements/': { results: [], count: 0 },
                '/api/projects/:team_id/announcements/channels/': [
                    { id: 'C1', name: 'acme', is_member: true, customer_name: 'Acme' },
                ],
            },
            post: {
                '/api/projects/:team_id/announcements/': {
                    id: '1',
                    short_id: 'abc123',
                    message: 'Offsite this week',
                    status: 'pending',
                    total_channels: 1,
                    sent_count: 0,
                    failed_count: 0,
                    sent_at: null,
                    created_at: '2026-01-01T00:00:00Z',
                    created_by: null,
                    deliveries: [],
                },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_settings: { slack_enabled: true } })
        mockPerformQuery.mockReset()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads customer-labeled member channels on mount when Slack is connected', async () => {
        logic = announcementsLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadMemberChannels', 'loadMemberChannelsSuccess'])
            .toMatchValues({
                memberChannels: [{ id: 'C1', name: 'acme', is_member: true, customer_name: 'Acme' }],
                channelOptions: [{ key: 'C1', label: 'Acme (#acme)' }],
            })
    })

    it('loads channels when Slack connects after mount, not only at mount time', async () => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_settings: { slack_enabled: false } })
        logic = announcementsLogic()
        logic.mount()
        await expectLogic(logic).toMatchValues({ slackConnected: false })
        expect(logic.values.memberChannels).toEqual([])

        await expectLogic(logic, () => {
            teamLogic.actions.loadCurrentTeamSuccess({
                ...MOCK_DEFAULT_TEAM,
                conversations_settings: { slack_enabled: true },
            })
        }).toDispatchActions(['loadMemberChannels', 'loadMemberChannelsSuccess'])
        expect(logic.values.memberChannels).toHaveLength(1)
    })

    it('blocks submit with an empty message', async () => {
        logic = announcementsLogic()
        logic.mount()
        await expectLogic(logic).toMatchValues({ submitDisabledReason: 'Enter a message' })
    })

    it('blocks submit when no channels are selected', async () => {
        logic = announcementsLogic()
        logic.mount()
        logic.actions.setMessage('Offsite this week')
        await expectLogic(logic).toMatchValues({ submitDisabledReason: 'Select at least one channel' })
    })

    it('submits, clears the draft, and reloads history', async () => {
        logic = announcementsLogic()
        logic.mount()
        logic.actions.setMessage('Offsite this week')
        logic.actions.setSelectedChannelIds(['C1'])

        await expectLogic(logic, () => {
            logic.actions.submitAnnouncement()
        })
            .toDispatchActions(['submitAnnouncement', 'loadAnnouncements'])
            .toFinishAllListeners()

        expect(logic.values.messageDraft).toBe('')
        expect(logic.values.selectedChannelIds).toEqual([])
        expect(logic.values.submitting).toBe(false)
    })

    it('narrows the channel picker to filtered accounts and bulk-selects them', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/announcements/': { results: [], count: 0 },
                '/api/projects/:team_id/announcements/channels/': [
                    { id: 'C1', name: 'acme', is_member: true, customer_name: 'Acme' },
                    { id: 'C3', name: 'globex', is_member: true, customer_name: 'Globex' },
                ],
            },
        })
        mockPerformQuery.mockResolvedValue({
            columns: ['name', 'slack_channel_id'],
            results: [
                [['Acme', 'ext-a', 'id-a'], 'C1'],
                [['Beta', 'ext-b', 'id-b'], 'C2'], // matched account whose channel the bot isn't in
                [['NoChannel', 'ext-n', 'id-n'], ''], // matched account with no channel
            ],
        })
        logic = announcementsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMemberChannelsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setAccountTags(['Enterprise'])
        }).toDispatchActions(['loadFilteredAccountChannelsSuccess'])

        const source = mockPerformQuery.mock.calls[0][0]
        expect(source.tagNames).toEqual(['Enterprise'])
        expect(source.select[0]).toContain("JSONExtractString(properties, 'slack_channel_id')")
        // Request beyond the default 100-row page so a large match set isn't truncated.
        expect(source.limit).toBe(50000)

        // Only member channels whose account matched survive: C3 (member, unmatched)
        // and C2 (matched, non-member) both drop.
        expect(logic.values.filteredChannelIds).toEqual(['C1'])
        expect(logic.values.filteredChannels).toEqual([{ key: 'C1', label: 'Acme (#acme)' }])
        expect(logic.values.channelOptions).toEqual([{ key: 'C1', label: 'Acme (#acme)' }])

        logic.actions.selectAllFilteredChannels()
        expect(logic.values.selectedChannelIds).toEqual(['C1'])
    })

    it('toggles an individual channel on and off', async () => {
        logic = announcementsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadMemberChannelsSuccess'])

        logic.actions.toggleChannel('C1')
        expect(logic.values.selectedChannelIds).toEqual(['C1'])

        logic.actions.toggleChannel('C9')
        expect(logic.values.selectedChannelIds).toEqual(['C1', 'C9'])

        logic.actions.toggleChannel('C1')
        expect(logic.values.selectedChannelIds).toEqual(['C9'])
    })

    it('treats "my accounts" as the current user and keeps assigned/unassigned mutually exclusive', async () => {
        mockPerformQuery.mockResolvedValue({ columns: ['name', 'slack_channel_id'], results: [] })
        logic = announcementsLogic()
        logic.mount()
        userLogic.actions.loadUserSuccess({ id: 7, email: 'me@example.com' } as UserType)

        logic.actions.setMyAccounts(true)
        expect(logic.values.assignedTo).toEqual([7])
        expect(logic.values.assignedToCurrentUser).toBe(true)

        logic.actions.setAllUnassigned(true)
        expect(logic.values.assignedTo).toEqual([])
        expect(logic.values.assignedToCurrentUser).toBe(false)

        logic.actions.setAssignedTo([9])
        expect(logic.values.allUnassigned).toBe(false)
    })

    it('does not submit while a send is already in flight', async () => {
        logic = announcementsLogic()
        logic.mount()
        logic.actions.setMessage('Offsite this week')
        logic.actions.setSelectedChannelIds(['C1'])
        logic.actions.setSubmitting(true)

        await expectLogic(logic, () => {
            logic.actions.submitAnnouncement()
        }).toFinishAllListeners()

        expect(logic.values.messageDraft).toBe('Offsite this week')
        expect(logic.values.selectedChannelIds).toEqual(['C1'])
    })
})
