import { commonUserId, insertRow, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, PropertyOperator, RawAction } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { PostgresUse } from '../../utils/db/postgres'
import { ActionManager } from './action-manager'

describe('ActionManager', () => {
    let hub: Hub
    let actionManager: ActionManager

    const TEAM_ID = 2
    const ACTION_ID = 69

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()

        await insertRow(hub.postgres, 'posthog_action', {
            id: ACTION_ID,
            team_id: TEAM_ID,
            name: 'Test Action',
            description: '',
            created_at: new Date().toISOString(),
            created_by_id: commonUserId,
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
        const action = actionManager.getTeamActions(TEAM_ID)

        expect(Object.values(action!).length).toEqual(1)
        expect(action![ACTION_ID]).toMatchObject({
            id: ACTION_ID,
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
            [ACTION_ID],
            'testKey'
        )

        await actionManager.reloadAction(TEAM_ID, ACTION_ID)

        const reloadedAction = actionManager.getTeamActions(TEAM_ID)

        expect(Object.values(action!).length).toEqual(1)
        expect(reloadedAction![ACTION_ID]).toMatchObject({
            id: ACTION_ID,
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

        actionManager.dropAction(TEAM_ID, ACTION_ID)

        const droppedAction = actionManager.getTeamActions(TEAM_ID)

        expect(Object.values(droppedAction!).length).toEqual(0)
    })

    it('returns the correct actions when deleted = TRUE', async () => {
        const action = actionManager.getTeamActions(TEAM_ID)

        expect(Object.values(action!).length).toEqual(1)
        expect(action![ACTION_ID]).toMatchObject({
            id: ACTION_ID,
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
            [ACTION_ID],
            'testKey'
        )

        await actionManager.reloadAction(TEAM_ID, ACTION_ID)

        const droppedAction = actionManager.getTeamActions(TEAM_ID)

        expect(Object.values(droppedAction!).length).toEqual(0)
    })
})
