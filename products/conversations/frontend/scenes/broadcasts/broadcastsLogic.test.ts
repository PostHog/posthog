import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { broadcastsLogic } from './broadcastsLogic'

describe('broadcastsLogic', () => {
    let logic: ReturnType<typeof broadcastsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/conversations/broadcasts/': { results: [], count: 0 },
            },
            post: {
                '/api/projects/:team_id/conversations/broadcasts/': (req: any) => [
                    201,
                    {
                        id: '1',
                        short_id: 'abc123',
                        message: req.body.message,
                        status: 'pending',
                        total_channels: req.body.channels.length,
                        sent_count: 0,
                        failed_count: 0,
                        sent_at: null,
                        created_at: '2026-01-01T00:00:00Z',
                        created_by: null,
                        deliveries: [],
                    },
                ],
                '/api/conversations/v1/slack/channels/': { channels: [{ id: 'C1', name: 'general', is_member: true }] },
            },
        })
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, conversations_settings: { slack_enabled: true } })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads member channels on mount when Slack is connected', async () => {
        logic = broadcastsLogic()
        logic.mount()
        await expectLogic(logic)
            .toDispatchActions(['loadMemberChannels', 'loadMemberChannelsSuccess'])
            .toMatchValues({ memberChannels: [{ id: 'C1', name: 'general', is_member: true }] })
    })

    it('blocks submit with an empty message', async () => {
        logic = broadcastsLogic()
        logic.mount()
        await expectLogic(logic).toMatchValues({ submitDisabledReason: 'Enter a message' })
    })

    it('blocks submit when no channels are selected', async () => {
        logic = broadcastsLogic()
        logic.mount()
        logic.actions.setMessage('Hello team')
        await expectLogic(logic).toMatchValues({ submitDisabledReason: 'Select at least one channel' })
    })

    it('submits, clears the draft, and reloads history', async () => {
        logic = broadcastsLogic()
        logic.mount()
        logic.actions.setMessage('Hello team')
        logic.actions.setSelectedChannelIds(['C1'])

        await expectLogic(logic, () => {
            logic.actions.submitBroadcast()
        })
            .toDispatchActions(['submitBroadcast', 'setSubmitting', 'loadBroadcasts'])
            .toFinishAllListeners()

        await expectLogic(logic).toMatchValues({
            messageDraft: '',
            selectedChannelIds: [],
            submitting: false,
        })
    })

    it('does not submit while a send is already in flight', async () => {
        logic = broadcastsLogic()
        logic.mount()
        logic.actions.setMessage('Hello team')
        logic.actions.setSelectedChannelIds(['C1'])
        logic.actions.setSubmitting(true)

        await expectLogic(logic, () => {
            logic.actions.submitBroadcast()
        }).toFinishAllListeners()

        // The guard returned early, so the draft is preserved (not cleared by a successful send).
        expect(logic.values.messageDraft).toBe('Hello team')
        expect(logic.values.selectedChannelIds).toEqual(['C1'])
    })
})
