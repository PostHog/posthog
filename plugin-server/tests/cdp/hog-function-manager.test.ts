import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
import { HogFunctionType } from '../../src/cdp/types'
import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { PostgresUse } from '../../src/utils/db/postgres'
import { createTeam, resetTestDatabase } from '../helpers/sql'
import { insertHogFunction } from './fixtures'

describe('HogFunctionManager', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let manager: HogFunctionManager

    let hogFunctions: HogFunctionType[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionManager(hub.postgres, hub)

        const team = await hub.db.fetchTeam(2)

        teamId1 = await createTeam(hub.db.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.db.postgres, team!.organization_id)

        hogFunctions = []
        hogFunctions.push(
            await insertHogFunction(hub.postgres, teamId1, {
                name: 'Test Hog Function team 1',
            })
        )

        hogFunctions.push(
            await insertHogFunction(hub.postgres, teamId2, {
                name: 'Test Hog Function team 2',
            })
        )

        await manager.start()
    })

    afterEach(async () => {
        await closeServer()
    })

    it('returns the hog functions', async () => {
        let functionsMap = manager.getTeamHogFunctions(teamId1)

        expect(functionsMap).toEqual({
            [hogFunctions[0].id]: {
                id: hogFunctions[0].id,
                team_id: teamId1,
                name: 'Test Hog Function team 1',
                enabled: true,
                inputs: null,
                bytecode: null,
                filters: null,
            },
        })

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET name='Test Hog Function team 1 updated' WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        await manager.reloadHogFunctions(teamId1, [hogFunctions[0].id])

        functionsMap = manager.getTeamHogFunctions(teamId1)

        expect(functionsMap[hogFunctions[0].id]).toMatchObject({
            id: hogFunctions[0].id,
            name: 'Test Hog Function team 1 updated',
        })
    })

    it('removes disabled functions', async () => {
        let functionsMap = manager.getTeamHogFunctions(teamId1)

        expect(functionsMap).toHaveProperty(hogFunctions[0].id)

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET enabled=false WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        await manager.reloadHogFunctions(teamId1, [hogFunctions[0].id])

        functionsMap = manager.getTeamHogFunctions(teamId1)

        expect(functionsMap).not.toHaveProperty(hogFunctions[0].id)
    })
})
