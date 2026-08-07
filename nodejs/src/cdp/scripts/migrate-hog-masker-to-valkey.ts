import IORedis, { Redis, RedisOptions } from 'ioredis'
import { parseArgs } from 'node:util'

import { stringToBoolean } from '~/common/utils/env-utils'

import { getDefaultCdpConfig } from '../config'
import {
    DEFAULT_KEY_PATTERN,
    MaskerMigrationOptions,
    MigrationPhase,
    formatMigrationSummary,
    migrationHasDrift,
    runMaskerMigration,
} from './hog-masker-valkey-migration'

const PHASES: MigrationPhase[] = ['stats', 'copy', 'check']

// The image ships dist rather than src, and an exec lands in /code, so that is the path to document.
const USAGE = `Usage: node nodejs/dist/cdp/scripts/migrate-hog-masker-to-valkey.js [options]

Copies HogMasker counters from the CDP Redis to the shadow Valkey. Counters are created with
SET NX, so a key the mirror is already maintaining is never overwritten and writers can keep
running throughout. Nothing here pauses or blocks CDP.

Phases:
  --phase stats   Count masking keys, how many the target already has, and their remaining
                  time to live (default). Read-only.
  --phase copy    Create the keys the target is missing. Reports what it would do unless
                  --execute is passed.
  --phase check   Compare values and expiries in both directions and report drift. Read-only,
                  and exits 2 when it finds any, so it can be scripted.

Options:
  --execute               Apply a copy. Rejected for the read-only phases.
  --pattern <glob>        Narrow the scan, e.g. to one hog function. Must start with the
                          masker key prefix (default: ${DEFAULT_KEY_PATTERN})
  --limit <n>             Stop after n scanned keys. Use this to size a run to a pod session.
  --scan-count <n>        SCAN batch size (default: 500)
  --sleep-ms <n>          Pause between batches to keep load off the source (default: 0)
  --ttl-tolerance-ms <n>  Expiry difference --phase check tolerates (default: 2000)
  --samples <n>           Example keys to print per drift bucket (default: 5)
  --json                  Print the summary as JSON instead of text

Connections are read from the same environment the CDP services use, so this works as-is
inside a running CDP pod:
  source  CDP_REDIS_HOST, CDP_REDIS_PORT, CDP_REDIS_PASSWORD (or REDIS_URL)
  target  CDP_VALKEY_HOST, CDP_VALKEY_PORT, CDP_VALKEY_PASSWORD, CDP_VALKEY_TLS`

const cdpDefaults = getDefaultCdpConfig()

type Endpoint = {
    label: string
    /** Host or full URL, matching what the CDP services hand to ioredis. */
    connection: string
    options: RedisOptions
}

function envString(key: string, fallback: string): string {
    return process.env[key] ?? fallback
}

function envNumber(key: string, fallback: number): number {
    const raw = process.env[key]
    if (raw === undefined || raw === '') {
        return fallback
    }
    const value = Number(raw)
    if (!Number.isFinite(value)) {
        throw new Error(`${key} must be a number, got: ${raw}`)
    }
    return value
}

function sourceEndpoint(): Endpoint {
    const password = envString('CDP_REDIS_PASSWORD', cdpDefaults.CDP_REDIS_PASSWORD) || undefined
    const host = envString('CDP_REDIS_HOST', cdpDefaults.CDP_REDIS_HOST)
    if (host) {
        return {
            label: 'source Redis',
            connection: host,
            options: { port: envNumber('CDP_REDIS_PORT', cdpDefaults.CDP_REDIS_PORT), password },
        }
    }
    // Same fallback order as createCdpCoreServices, so a pod without CDP_REDIS_HOST still resolves.
    const url = process.env.REDIS_URL
    if (!url) {
        throw new Error('Set CDP_REDIS_HOST or REDIS_URL to point at the source Redis')
    }
    return { label: 'source Redis', connection: url, options: {} }
}

function targetEndpoint(): Endpoint {
    const host = envString('CDP_VALKEY_HOST', cdpDefaults.CDP_VALKEY_HOST)
    if (!host) {
        throw new Error('Set CDP_VALKEY_HOST to point at the target Valkey')
    }
    return {
        label: 'target Valkey',
        connection: host,
        options: {
            port: envNumber('CDP_VALKEY_PORT', cdpDefaults.CDP_VALKEY_PORT),
            password: envString('CDP_VALKEY_PASSWORD', cdpDefaults.CDP_VALKEY_PASSWORD) || undefined,
            tls: stringToBoolean(envString('CDP_VALKEY_TLS', String(cdpDefaults.CDP_VALKEY_TLS))) ? {} : undefined,
        },
    }
}

/** Host and port only — a password can be embedded in a REDIS_URL and must not reach the logs. */
function describeEndpoint(endpoint: Endpoint): string {
    try {
        return new URL(endpoint.connection).host
    } catch {
        return `${endpoint.connection}:${endpoint.options.port ?? 6379}`
    }
}

function connect(endpoint: Endpoint): Redis {
    return new IORedis(endpoint.connection, { ...endpoint.options, lazyConnect: true, maxRetriesPerRequest: 3 })
}

function positiveInteger(name: string, raw: string): number {
    const value = Number(raw)
    if (!Number.isInteger(value) || value < 1) {
        throw new Error(`${name} must be a positive integer, got: ${raw}`)
    }
    return value
}

function nonNegativeInteger(name: string, raw: string): number {
    const value = Number(raw)
    if (!Number.isInteger(value) || value < 0) {
        throw new Error(`${name} must be zero or a positive integer, got: ${raw}`)
    }
    return value
}

function parseOptions(): { options: MaskerMigrationOptions; json: boolean } {
    const { values } = parseArgs({
        options: {
            phase: { type: 'string', default: 'stats' },
            execute: { type: 'boolean', default: false },
            pattern: { type: 'string', default: DEFAULT_KEY_PATTERN },
            limit: { type: 'string' },
            'scan-count': { type: 'string', default: '500' },
            'sleep-ms': { type: 'string', default: '0' },
            'ttl-tolerance-ms': { type: 'string', default: '2000' },
            samples: { type: 'string', default: '5' },
            json: { type: 'boolean', default: false },
            help: { type: 'boolean', default: false },
        },
    })
    if (values.help) {
        console.log(USAGE)
        process.exit(0)
    }
    if (!PHASES.includes(values.phase as MigrationPhase)) {
        throw new Error(`Invalid --phase: ${values.phase}. Expected one of ${PHASES.join(', ')}`)
    }
    const phase = values.phase as MigrationPhase
    if (values.execute && phase !== 'copy') {
        throw new Error(`--execute only applies to --phase copy; --phase ${phase} never writes`)
    }
    return {
        json: values.json,
        options: {
            phase,
            execute: values.execute,
            keyPattern: values.pattern,
            scanCount: positiveInteger('--scan-count', values['scan-count']),
            limit: values.limit === undefined ? null : positiveInteger('--limit', values.limit),
            sleepMsBetweenBatches: nonNegativeInteger('--sleep-ms', values['sleep-ms']),
            ttlToleranceMs: nonNegativeInteger('--ttl-tolerance-ms', values['ttl-tolerance-ms']),
            sampleKeysPerBucket: nonNegativeInteger('--samples', values.samples),
        },
    }
}

async function main(): Promise<void> {
    const { options, json } = parseOptions()
    const source = sourceEndpoint()
    const target = targetEndpoint()
    if (describeEndpoint(source) === describeEndpoint(target)) {
        throw new Error('Source Redis and target Valkey resolve to the same endpoint')
    }

    const sourceClient = connect(source)
    const targetClient = connect(target)
    try {
        await Promise.all([sourceClient.connect(), targetClient.connect()])
        await Promise.all([sourceClient.ping(), targetClient.ping()])
        if (!json) {
            console.log(`${source.label} ${describeEndpoint(source)} -> ${target.label} ${describeEndpoint(target)}`)
        }

        const summary = await runMaskerMigration(sourceClient, targetClient, options)
        console.log(json ? JSON.stringify(summary) : formatMigrationSummary(summary, options.keyPattern))
        if (options.phase === 'check' && migrationHasDrift(summary)) {
            process.exitCode = 2
        }
    } finally {
        await Promise.allSettled([sourceClient.quit(), targetClient.quit()])
    }
}

void main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
})
