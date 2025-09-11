import { Hub, PropertyOperator } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { ActionManager } from '../../../src/worker/ingestion/action-manager'
import { resetTestDatabase } from '../../helpers/sql'

describe('ActionManager', () => {
    let hub: Hub
    let actionManager: ActionManager

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        actionManager = new ActionManager(hub.postgres, hub.pubSub)
        await actionManager.start()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    const TEAM_ID = 2
    const ACTION_ID = 69

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

        await hub.db.postgres.query(
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

        await hub.db.postgres.query(
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

    it('does nothing when no `processAsyncWebhooksHandlers` capabilities', async () => {
        jest.spyOn(hub.db, 'fetchAllActionsGroupedByTeam')
        jest.spyOn(hub.db, 'fetchAction')

        const manager = new ActionManager(hub.postgres, hub.pubSub)

        await manager.start()
        await manager.reloadAllActions()
        await manager.reloadAction(TEAM_ID, ACTION_ID)

        expect(hub.db.fetchAllActionsGroupedByTeam).not.toHaveBeenCalled()
        expect(hub.db.fetchAction).not.toHaveBeenCalled()
    })
})
