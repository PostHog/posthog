import { parseArgs } from 'node:util'

import { defaultConfig } from '~/common/config/config'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import { createCdpProducerRegistry } from '../../../outputs/producer-registry'
import { WARPSTREAM_INGESTION_PRODUCER } from '../../../outputs/producers'
import { CohortMembershipBackfill } from '../membership-backfill'

/**
 * Copies current cohort members from Postgres to the ClickHouse `realtime_cohort_membership` table,
 * through the membership topic.
 *
 * Run it in a `cdp-cohort-membership-consumer` pod, which already has the database URL and the
 * producer config. From `/code`:
 * `node nodejs/dist/cdp/services/cohort-membership/scripts/backfill-membership-to-clickhouse.js`
 * Options: `--team-id <id>`, `--batch-size <rows>` (default 1000), `--pause-ms <ms>` (default 100).
 *
 * Every consumer pod must run a release that skips backfill changes first. A pod without the skip
 * rewrites each member row, and turns a `-infinity` version into the epoch.
 */
async function main(): Promise<void> {
    const { values } = parseArgs({
        options: {
            'team-id': { type: 'string' },
            'batch-size': { type: 'string', default: '1000' },
            'pause-ms': { type: 'string', default: '100' },
        },
    })

    const postgres = new PostgresRouter(defaultConfig)
    const producers = await createCdpProducerRegistry(defaultConfig.KAFKA_CLIENT_RACK).build(defaultConfig)

    try {
        const published = await new CohortMembershipBackfill(
            postgres,
            producers.getProducer(WARPSTREAM_INGESTION_PRODUCER)
        ).run({
            teamId: values['team-id'] === undefined ? null : Number(values['team-id']),
            batchSize: Number(values['batch-size']),
            pauseMs: Number(values['pause-ms']),
        })
        logger.info('Finished the ClickHouse cohort membership backfill', { published })
    } finally {
        await producers.disconnectAll()
        await postgres.end()
    }
}

main().catch((error) => {
    logger.error('The ClickHouse cohort membership backfill failed', { error: String(error) })
    process.exit(1)
})
