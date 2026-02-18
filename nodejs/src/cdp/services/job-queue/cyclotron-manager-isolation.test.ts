/**
 * Integration test to verify CyclotronManager and CyclotronShadowManager
 * write to separate databases. This tests the fix for the singleton collision
 * bug where both managers would write to whichever database was initialized first.
 */
import { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

import { CyclotronManager, CyclotronShadowManager } from '@posthog/cyclotron'

const TEST_CYCLOTRON_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron'
const TEST_CYCLOTRON_SHADOW_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_shadow'

describe('CyclotronManager isolation', () => {
    jest.setTimeout(10000)

    let mainPool: Pool
    let shadowPool: Pool

    beforeAll(() => {
        mainPool = new Pool({ connectionString: TEST_CYCLOTRON_URL })
        shadowPool = new Pool({ connectionString: TEST_CYCLOTRON_SHADOW_URL })
    })

    afterAll(async () => {
        await mainPool.end()
        await shadowPool.end()
    })

    beforeEach(async () => {
        // Clean up jobs from both databases
        await mainPool.query('DELETE FROM cyclotron_jobs')
        await shadowPool.query('DELETE FROM cyclotron_jobs')
    })

    it('should write to separate databases when both managers are initialized', async () => {
        // Initialize both managers - order matters, this is what caused the original bug
        const mainManager = new CyclotronManager({
            shards: [{ dbUrl: TEST_CYCLOTRON_URL }],
        })
        const shadowManager = new CyclotronShadowManager({
            shards: [{ dbUrl: TEST_CYCLOTRON_SHADOW_URL }],
        })

        await mainManager.connect()
        await shadowManager.connect()

        // Create unique IDs to identify which job went where
        const mainJobId = uuidv4()
        const shadowJobId = uuidv4()

        // Write a job through the main manager
        await mainManager.createJob({
            id: mainJobId,
            teamId: 1,
            functionId: uuidv4(),
            queueName: 'hog',
            priority: 1,
        })

        // Write a job through the shadow manager
        await shadowManager.createJob({
            id: shadowJobId,
            teamId: 1,
            functionId: uuidv4(),
            queueName: 'hog',
            priority: 1,
        })

        // Query both databases to verify isolation
        const mainDbJobs = await mainPool.query('SELECT id FROM cyclotron_jobs')
        const shadowDbJobs = await shadowPool.query('SELECT id FROM cyclotron_jobs')

        // Main DB should only have the main job
        expect(mainDbJobs.rows).toHaveLength(1)
        expect(mainDbJobs.rows[0].id).toBe(mainJobId)

        // Shadow DB should only have the shadow job
        expect(shadowDbJobs.rows).toHaveLength(1)
        expect(shadowDbJobs.rows[0].id).toBe(shadowJobId)
    })

    it('should write bulk jobs to separate databases', async () => {
        const mainManager = new CyclotronManager({
            shards: [{ dbUrl: TEST_CYCLOTRON_URL }],
        })
        const shadowManager = new CyclotronShadowManager({
            shards: [{ dbUrl: TEST_CYCLOTRON_SHADOW_URL }],
        })

        await mainManager.connect()
        await shadowManager.connect()

        const mainJobIds = [uuidv4(), uuidv4()]
        const shadowJobIds = [uuidv4(), uuidv4(), uuidv4()]

        // Bulk create jobs through main manager
        await mainManager.bulkCreateJobs(
            mainJobIds.map((id) => ({
                id,
                teamId: 1,
                functionId: uuidv4(),
                queueName: 'hog',
                priority: 1,
            }))
        )

        // Bulk create jobs through shadow manager
        await shadowManager.bulkCreateJobs(
            shadowJobIds.map((id) => ({
                id,
                teamId: 1,
                functionId: uuidv4(),
                queueName: 'hog',
                priority: 1,
            }))
        )

        // Query both databases
        const mainDbJobs = await mainPool.query('SELECT id FROM cyclotron_jobs ORDER BY id')
        const shadowDbJobs = await shadowPool.query('SELECT id FROM cyclotron_jobs ORDER BY id')

        // Verify counts
        expect(mainDbJobs.rows).toHaveLength(2)
        expect(shadowDbJobs.rows).toHaveLength(3)

        // Verify the right jobs are in each database
        const mainDbJobIds = mainDbJobs.rows.map((r) => r.id).sort()
        const shadowDbJobIds = shadowDbJobs.rows.map((r) => r.id).sort()

        expect(mainDbJobIds).toEqual(mainJobIds.sort())
        expect(shadowDbJobIds).toEqual(shadowJobIds.sort())
    })
})
