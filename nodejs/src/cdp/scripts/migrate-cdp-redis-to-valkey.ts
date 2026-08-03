import IORedis, { Redis } from 'ioredis'
import { parseArgs } from 'node:util'

import {
    CdpMigrationOptions,
    MigrationPhase,
    migrationHasMismatches,
    runCdpMigration,
} from './cdp-valkey-migration'

const KEY_PATTERNS = [
    '@posthog/hog-masker/mask/*',
    '@posthog/hog-watcher-2/state/*',
    '@posthog/hog-watcher-2/tokens/*',
    '@posthog/hog-watcher-2/state-lock/*',
]

function connectionFromEnv(prefix: 'CDP_REDIS' | 'CDP_VALKEY'): Redis {
    const host = process.env[`${prefix}_HOST`]
    if (!host) {
        throw new Error(`${prefix}_HOST is required`)
    }
    const port = Number(process.env[`${prefix}_PORT`] || '6379')
    const password = process.env[`${prefix}_PASSWORD`] || undefined
    const tls = process.env[`${prefix}_TLS`] === 'true' ? {} : undefined
    return new IORedis({ host, port, password, tls, lazyConnect: true, maxRetriesPerRequest: 3 })
}

function parseOptions(): CdpMigrationOptions {
    const { values } = parseArgs({
        options: {
            phase: { type: 'string', default: 'copy' },
            execute: { type: 'boolean', default: false },
            'writers-paused': { type: 'boolean', default: false },
            'scan-count': { type: 'string', default: '500' },
            'ttl-tolerance-ms': { type: 'string', default: '2000' },
            help: { type: 'boolean', default: false },
        },
    })
    if (values.help) {
        console.log(`Usage: migrate-cdp-redis-to-valkey [options]

  --phase copy       Copy source keys while Redis remains authoritative (default)
  --phase finalize   Exact copy and remove target-only keys; requires paused writers
  --phase verify     Compare values and expiries without writing
  --execute          Apply changes; omitted means dry-run
  --writers-paused   Confirm every HogMasker and HogWatcher writer is paused
  --scan-count N     Redis SCAN batch size (default: 500)
  --ttl-tolerance-ms N  Allowed expiry difference during verify (default: 2000)

Connections come from CDP_REDIS_* (source) and CDP_VALKEY_* (target).`)
        process.exit(0)
    }
    if (!['copy', 'finalize', 'verify'].includes(values.phase)) {
        throw new Error(`Invalid --phase: ${values.phase}`)
    }
    const scanCount = Number(values['scan-count'])
    const ttlToleranceMs = Number(values['ttl-tolerance-ms'])
    if (!Number.isInteger(scanCount) || scanCount < 1 || !Number.isFinite(ttlToleranceMs) || ttlToleranceMs < 0) {
        throw new Error('Scan count must be a positive integer and TTL tolerance must be non-negative')
    }
    return {
        phase: values.phase as MigrationPhase,
        execute: values.execute,
        writersPaused: values['writers-paused'],
        scanCount,
        ttlToleranceMs,
        keyPatterns: KEY_PATTERNS,
    }
}

async function main(): Promise<void> {
    const options = parseOptions()
    const sourceHost = process.env.CDP_REDIS_HOST
    const targetHost = process.env.CDP_VALKEY_HOST
    if (
        sourceHost === targetHost &&
        (process.env.CDP_REDIS_PORT || '6379') === (process.env.CDP_VALKEY_PORT || '6379')
    ) {
        throw new Error('Source Redis and target Valkey must be different endpoints')
    }
    const source = connectionFromEnv('CDP_REDIS')
    const target = connectionFromEnv('CDP_VALKEY')
    try {
        await Promise.all([source.connect(), target.connect()])
        await Promise.all([source.ping(), target.ping()])
        const summary = await runCdpMigration(source, target, options)
        console.log(
            JSON.stringify({ phase: options.phase, dryRun: !options.execute, patterns: options.keyPatterns, ...summary })
        )
        if (migrationHasMismatches(summary)) {
            process.exitCode = 2
        }
    } finally {
        await Promise.allSettled([source.quit(), target.quit()])
    }
}

void main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
})
