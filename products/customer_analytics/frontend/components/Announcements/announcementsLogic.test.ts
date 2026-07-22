import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { announcementsLogic } from './announcementsLogic'

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
