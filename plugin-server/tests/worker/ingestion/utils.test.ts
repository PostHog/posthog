import { Hub, LogLevel } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { captureIngestionWarning } from '../../../src/worker/ingestion/utils'
import { delayUntilEventIngested, fetchIngestionWarnings } from '../../helpers/clickhouse'
import { createOrganization, createTeam } from '../../helpers/sql'

jest.setTimeout(60000) // 60 sec timeout

describe('captureIngestionWarning()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let teamId: number

    beforeAll(async () => {
        ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log, MAX_PENDING_PROMISES_PER_WORKER: 0 })
    })

    beforeEach(async () => {
        const organizationId = await createOrganization()
        teamId = await createTeam(organizationId)
    })

    afterAll(async () => {
        await closeHub()
    })

    it('can read own writes', async () => {
        captureIngestionWarning(hub.db, teamId, 'some_type', { foo: 'bar' })
        await hub.promiseManager.awaitPromisesIfNeeded()

        const warnings = await delayUntilEventIngested(() => fetchIngestionWarnings(teamId))
        expect(warnings).toEqual([
            expect.objectContaining({
                team_id: teamId,
                source: 'plugin-server',
                type: 'some_type',
                details: '{"foo":"bar"}',
                timestamp: expect.any(String),
                _timestamp: expect.any(String),
            }),
        ])
    })
})
