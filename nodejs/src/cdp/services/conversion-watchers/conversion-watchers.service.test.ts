import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'

import { ConversionWatcherRow, CyclotronJobInvocationResult } from '../../types'
import { ConversionWatchersService } from './conversion-watchers.service'

const DB_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

describe('ConversionWatchersService', () => {
    let service: ConversionWatchersService
    let assertPool: Pool

    beforeAll(() => {
        assertPool = new Pool({ connectionString: DB_URL })
    })

    afterAll(async () => {
        await assertPool.end()
    })

    beforeEach(() => {
        service = new ConversionWatchersService(DB_URL)
    })

    afterEach(async () => {
        await service.stop()
    })

    const watcherRow = (id: string): ConversionWatcherRow => ({
        id,
        team_id: 1,
        function_id: uuidv7(),
        run_id: id,
        parent_run_id: null,
        distinct_id: `distinct-${id}`,
        person_id: null,
        flow_version: 1,
        goal: { events: [['_H', 1, 29]] },
        expires_at: new Date(Date.now() + 3_600_000),
    })

    const resultFor = (
        runId: string,
        params: Pick<Partial<CyclotronJobInvocationResult>, 'conversionWatchers' | 'conversionWatcherVersion'>
    ): CyclotronJobInvocationResult => {
        const invocation = { ...createExampleHogFlowInvocation(new FixtureHogFlowBuilder().build()), id: runId }
        return createInvocationResult(invocation, {}, params)
    }

    const enrollment = (runId: string): CyclotronJobInvocationResult =>
        resultFor(runId, { conversionWatchers: [watcherRow(runId)] })

    const sendUnder = (runId: string, version: number): CyclotronJobInvocationResult =>
        resultFor(runId, { conversionWatcherVersion: version })

    const storedVersions = async (ids: string[]): Promise<Record<string, number | null>> => {
        const { rows } = await assertPool.query(
            `SELECT id, flow_version FROM conversion_watchers WHERE id = ANY($1::uuid[])`,
            [ids]
        )
        return Object.fromEntries(rows.map((row) => [row.id, row.flow_version]))
    }

    it.each([
        { name: 'a later flush', sameFlush: false },
        { name: 'the same flush', sameFlush: true },
    ])('moves a watcher to the version a send re-pinned in $name', async ({ sameFlush }) => {
        const id = uuidv7()

        if (sameFlush) {
            service.queueInvocationResults([enrollment(id), sendUnder(id, 2)])
        } else {
            service.queueInvocationResults([enrollment(id)])
            await service.flush()
            service.queueInvocationResults([sendUnder(id, 2)])
        }
        await service.flush()

        expect(await storedVersions([id])).toEqual({ [id]: 2 })
    })

    it.each([
        { name: 'a later flush', sameFlush: false },
        { name: 'the same flush', sameFlush: true },
    ])('keeps the newer version when an update from an earlier send lands in $name', async ({ sameFlush }) => {
        const id = uuidv7()
        const newer = sendUnder(id, 3)
        const stale = sendUnder(id, 2)

        if (sameFlush) {
            service.queueInvocationResults([enrollment(id), newer, stale])
        } else {
            service.queueInvocationResults([enrollment(id), newer])
            await service.flush()
            service.queueInvocationResults([stale])
        }
        await service.flush()

        expect(await storedVersions([id])).toEqual({ [id]: 3 })
    })

    it('does not bring back a watcher the matcher already claimed', async () => {
        const id = uuidv7()
        service.queueInvocationResults([enrollment(id)])
        await service.flush()
        await assertPool.query(`DELETE FROM conversion_watchers WHERE id = $1`, [id])

        service.queueInvocationResults([sendUnder(id, 2)])
        await service.flush()

        expect(await storedVersions([id])).toEqual({})
    })
})
