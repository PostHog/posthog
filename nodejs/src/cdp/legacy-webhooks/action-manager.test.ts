import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'

import { createTestTeamFixture, insertRow } from '../../../tests/helpers/sql'
import { Hub, PropertyOperator, RawAction } from '../../types'
import { ActionManager } from './action-manager'

describe('ActionManager', () => {
    let hub: Hub
    let actionManager: ActionManager

    let teamId: number
    let actionId: number
    let userId: number

    beforeEach(async () => {
        hub = await createHub()
        const fixture = await createTestTeamFixture(hub.postgres)
        teamId = fixture.team.id
        userId = fixture.userId
        actionId = teamId

        await insertRow(hub.postgres, 'posthog_action', {
            id: actionId,
            team_id: teamId,
            name: 'Test Action',
            description: '',
            created_at: new Date().toISOString(),
            created_by_id: userId,
            deleted: false,
            post_to_slack: true,
            slack_message_format: '',
            is_calculating: false,
            updated_at: new Date().toISOString(),
            last_calculated_at: new Date().toISOString(),
            steps_json: [
                {
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    event: null,
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                },
            ],
        } as RawAction)
        actionManager = new ActionManager(hub.postgres, hub.pubSub)
        await actionManager.start()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns the correct actions generally', async () => {
        const action = actionManager.getTeamActions(teamId)

        expect(Object.values(action!).length).toEqual(1)
        expect(action![actionId]).toMatchObject({
            id: actionId,
            name: 'Test Action',
            deleted: false,
            post_to_slack: true,
            slack_message_format: '',
            is_calculating: false,
            steps: [
                {
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    event: null,
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                },
            ],
        })

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_action SET slack_message_format='test' WHERE id = $1`,
            [actionId],
            'testKey'
        )

        await actionManager.reloadAction(teamId, actionId)

        const reloadedAction = actionManager.getTeamActions(teamId)

        expect(Object.values(action!).length).toEqual(1)
        expect(reloadedAction![actionId]).toMatchObject({
            id: actionId,
            name: 'Test Action',
            deleted: false,
            post_to_slack: true,
            slack_message_format: 'test',
            is_calculating: false,
            steps: [
                {
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    event: null,
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                },
            ],
        })

        actionManager.dropAction(teamId, actionId)

        const droppedAction = actionManager.getTeamActions(teamId)

        expect(Object.values(droppedAction!).length).toEqual(0)
    })

    it('returns the correct actions when deleted = TRUE', async () => {
        const action = actionManager.getTeamActions(teamId)

        expect(Object.values(action!).length).toEqual(1)
        expect(action![actionId]).toMatchObject({
            id: actionId,
            name: 'Test Action',
            deleted: false,
            post_to_slack: true,
            slack_message_format: '',
            is_calculating: false,
            steps: [
                {
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    event: null,
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                },
            ],
        })

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_action
             SET deleted = TRUE
             WHERE id = $1`,
            [actionId],
            'testKey'
        )

        await actionManager.reloadAction(teamId, actionId)

        const droppedAction = actionManager.getTeamActions(teamId)

        expect(Object.values(droppedAction!).length).toEqual(0)
    })
})
