import { Hub } from '../../../src/types'
import { createPluginActivityLog } from '../../../src/utils/db/activity-log'
import { createHub } from '../../../src/utils/db/hub'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

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
    let closeHub: () => Promise<void>
    let teamId: number
    let pluginConfigId: number

    beforeEach(async () => {
        ;({ teamId, pluginConfigId } = await resetTestDatabase())
        ;[hub, closeHub] = await createHub({})
    })

    afterEach(async () => {
        await closeHub()
    })

    async function fetchPluginActivityLogs(hub: Hub): Promise<Array<ActivityLog>> {
        const result = await hub.db.postgresQuery<ActivityLog>(
            `SELECT * FROM posthog_activitylog WHERE team_id = $1 AND scope = 'PluginConfig'`,
            [teamId],
            'fetchPluginActivityLogs'
        )
        return result.rows
    }

    it('can read own writes', async () => {
        await createPluginActivityLog(hub, teamId, pluginConfigId, 'job_finished', {
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
                team_id: teamId,
                organization_id: expect.any(String),
                user_id: null,
                is_system: true,
                activity: 'job_finished',
                item_id: String(pluginConfigId),
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
        await createPluginActivityLog(hub, -1, pluginConfigId, 'job_finished', {} as any)

        expect(await fetchPluginActivityLogs(hub)).toEqual([])
    })
})
