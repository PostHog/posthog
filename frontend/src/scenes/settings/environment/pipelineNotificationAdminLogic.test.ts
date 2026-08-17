import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { pipelineNotificationAdminLogic } from './pipelineNotificationAdminLogic'

const PIPELINE_ID = 'hog_function:0198aaaa-1111-4222-8333-444455556666'

const MEMBERS = [
    {
        user_id: 1,
        uuid: '0198aaaa-1111-4222-8333-000000000001',
        first_name: 'Ada',
        last_name: 'Member',
        email: 'ada@posthog.com',
        organization_membership_level: 1,
        editable: true,
        pipeline_emails_enabled: true,
        unsubscribed_pipeline_ids: [],
    },
    {
        user_id: 2,
        uuid: '0198aaaa-1111-4222-8333-000000000002',
        first_name: 'Grace',
        last_name: 'Owner',
        email: 'grace@posthog.com',
        organization_membership_level: 15,
        editable: false,
        pipeline_emails_enabled: true,
        unsubscribed_pipeline_ids: [],
    },
]

describe('pipelineNotificationAdminLogic', () => {
    let logic: ReturnType<typeof pipelineNotificationAdminLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/pipeline_notification_subscriptions/': MEMBERS,
                '/api/projects/:team_id/hog_functions/': { results: [], next: null },
                '/api/projects/:team_id/pipeline_destination_configs/': { results: [], next: null },
                '/api/projects/:team_id/batch_exports/': { results: [], next: null },
            },
        })
        initKeaTests()
        teamLogic.mount()
        logic = pipelineNotificationAdminLogic()
        logic.mount()
    })

    it('drops a change that puts a member back where they started', () => {
        logic.actions.loadMembersSuccess(MEMBERS)

        logic.actions.setSubscription(1, PIPELINE_ID, false)
        expect(logic.values.changesToSave).toEqual([{ user_id: 1, pipeline_id: PIPELINE_ID, subscribed: false }])
        expect(logic.values.affectedMemberCount).toBe(1)

        logic.actions.setSubscription(1, PIPELINE_ID, true)
        expect(logic.values.changesToSave).toEqual([])
        expect(logic.values.pendingChangeCount).toBe(0)
    })

    it('leaves members above your access level out of a bulk change', () => {
        logic.actions.loadMembersSuccess(MEMBERS)

        logic.actions.setSubscriptionForAllMembers(PIPELINE_ID, false)

        expect(logic.values.changesToSave).toEqual([{ user_id: 1, pipeline_id: PIPELINE_ID, subscribed: false }])
    })
})
