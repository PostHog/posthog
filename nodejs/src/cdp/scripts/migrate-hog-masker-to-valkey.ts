import IORedis, { Redis } from 'ioredis'
import { parseArgs } from 'node:util'

import {
    MaskerMigrationOptions,
    MigrationPhase,
    migrationHasMismatches,
    runMaskerMigration,
} from './hog-masker-valkey-migration'

const KEY_PATTERN = '@posthog/hog-masker/mask/*'

function requiredHost(prefix: 'CDP_REDIS' | 'CDP_VALKEY'): string {
    const host = process.env[`${prefix}_HOST`]
    if (!host) {
        throw new Error(`${prefix}_HOST is required`)
    }
    return host
}

function connectionFromEnv(prefix: 'CDP_REDIS' | 'CDP_VALKEY'): Redis {
    const host = requiredHost(prefix)
    const port = Number(process.env[`${prefix}_PORT`] || '6379')
    const password = process.env[`${prefix}_PASSWORD`] || undefined
    const tls = process.env[`${prefix}_TLS`] === 'true' ? {} : undefined
    return new IORedis({ host, port, password, tls, lazyConnect: true, maxRetriesPerRequest: 3 })
}

function parseOptions(): MaskerMigrationOptions {
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
        console.log(`Usage: migrate-hog-masker-to-valkey [options]

  --phase copy       Copy source keys while Redis remains authoritative (default)
  --phase finalize   Exact copy and remove target-only keys; requires paused writers
  --phase verify     Compare values and expiries without writing
  --execute          Apply changes; omitted means dry-run
  --writers-paused   Confirm every HogMasker writer is paused
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
        keyPattern: KEY_PATTERN,
    }
}

async function main(): Promise<void> {
    const options = parseOptions()
    // Resolve hosts before comparing them, so a missing host reports itself rather than looking like a duplicate endpoint.
    const sourceHost = requiredHost('CDP_REDIS')
    const targetHost = requiredHost('CDP_VALKEY')
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
        const summary = await runMaskerMigration(source, target, options)
        console.log(
            JSON.stringify({ phase: options.phase, dryRun: !options.execute, pattern: options.keyPattern, ...summary })
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
