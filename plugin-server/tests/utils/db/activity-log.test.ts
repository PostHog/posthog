import { Hub } from '../../../src/types'
import { createPluginActivityLog } from '../../../src/utils/db/activity-log'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { pluginConfig39 } from '../../helpers/plugins'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/logger')

interface ActivityLog {
    team_id: number | null
    organization_id: number | null
    user_id: number | null
    is_system: boolean | null

    scope: string
    item_id: string
    details: Record<string, any>

    created_at: string
}

describe('createPluginActivityLog()', () => {
    let hub: Hub

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub({})
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    async function fetchPluginActivityLogs(hub: Hub): Promise<Array<ActivityLog>> {
        const result = await hub.db.postgres.query<ActivityLog>(
            PostgresUse.COMMON_READ,
            `SELECT * FROM posthog_activitylog`,
            [],
            'fetchPluginActivityLogs'
        )
        return result.rows
    }

    it('can read own writes', async () => {
        await createPluginActivityLog(hub, pluginConfig39.team_id, pluginConfig39.id, 'job_finished', {
            trigger: {
                job_id: 'foobar',
                job_type: 'some_type',
                payload: { value: 5 },
            },
        })

        const activityLogs = await fetchPluginActivityLogs(hub)
        expect(activityLogs).toEqual([
            expect.objectContaining({
                id: expect.any(String),
                team_id: pluginConfig39.team_id,
                organization_id: expect.any(String),
                user_id: null,
                is_system: true,
                activity: 'job_finished',
                item_id: String(pluginConfig39.id),
                scope: 'PluginConfig',
                detail: {
                    trigger: {
                        job_id: 'foobar',
                        job_type: 'some_type',
                        payload: { value: 5 },
                    },
                },
                created_at: expect.any(String),
            }),
        ])
    })

    it('does not blow up for an invalid team', async () => {
        await createPluginActivityLog(hub, -1, pluginConfig39.id, 'job_finished', {} as any)

        expect(await fetchPluginActivityLogs(hub)).toEqual([])
    })
})
