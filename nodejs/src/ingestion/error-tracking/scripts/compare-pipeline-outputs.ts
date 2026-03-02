#!/usr/bin/env npx ts-node
/**
 * Compares exception event outputs between the original Cymbal consumer and the new nodejs pipeline.
 *
 * Usage:
 *   # First, configure nodejs to output to a different topic:
 *   ERROR_TRACKING_CONSUMER_OUTPUT_TOPIC=clickhouse_events_json_nodejs_test pnpm start:dev
 *
 *   # Then run this script to compare outputs:
 *   npx ts-node src/ingestion/error-tracking/scripts/compare-pipeline-outputs.ts
 *
 * Options:
 *   --duration <seconds>    How long to collect events (default: 30)
 *   --original-topic <name> Original pipeline topic (default: clickhouse_events_json)
 *   --nodejs-topic <name>   Nodejs pipeline topic (default: clickhouse_events_json_nodejs_test)
 *   --brokers <list>        Kafka brokers (default: localhost:9092)
 */
import { KafkaConsumer, Message } from 'node-rdkafka'

import { parseJSON } from '~/utils/json-parse'

// Distinct IDs that have real persons in the database (team_id=1)
// When events use these distinct_ids, both pipelines should have matching person data
const DISTINCT_IDS_WITH_PERSONS = new Set([
    'fb5f7ba4-054d-da20-7b8a-8a2142eb3764', // Arnold Hughes
    'uSfLKYzNuDveSYKE', // Arnold Hughes (same person)
    '27ff2c8a-0dd0-7c82-1786-f1023c3b2be9',
    'f636672d-5c84-d4d1-cf1c-84b4d51f5260',
    '3b366cfc-3506-3210-02d7-1546031c8aa3',
    'd0514dea-9f79-1776-5207-9b595e3a5f30',
    'ef9757aa-667f-8556-88b2-f5d109585b0d',
    '33c07e30-bd2c-781b-9b59-ecf882cbfed1',
    'e8c9fbc8-2ee0-93e5-e846-ed8d0d45dc1b',
    'xhZMaphskRWXPREp', // Tanja Hooper (same person as above)
])

// Person-related fields that differ when no person is found:
// - Cymbal omits these fields entirely
// - Node includes placeholder values
const PERSON_FIELDS = new Set(['person_id', 'person_properties', 'person_created_at'])

// Fields to always ignore when comparing events
const IGNORED_FIELDS = new Set([
    // Timestamps that are set at processing time (will always differ slightly)
    'created_at',
    // Cymbal never sets captured_at, Node always does
    'captured_at',
    // Kafka metadata (not part of the event schema)
    '_timestamp',
    '_offset',
    '_partition',
])

// Property fields to ignore - these are added by Hog transformer but not by Cymbal
// They represent enhancements in the Node.js pipeline that we accept as expected differences
const IGNORED_PROPERTY_FIELDS = new Set([
    // Hog transformer metadata
    '$transformations_succeeded',
    // Extra GeoIP fields added by Hog transformer but not by Cymbal's GeoIP
    // Cymbal only adds: country_name, city_name, country_code, continent_name, continent_code, postal_code, time_zone
    '$geoip_latitude',
    '$geoip_longitude',
    '$geoip_accuracy_radius',
    '$geoip_subdivision_1_code',
    '$geoip_subdivision_1_name',
    '$geoip_subdivision_2_code',
    '$geoip_subdivision_2_name',
    '$geoip_city_confidence',
])

// Path patterns to ignore - these are fields generated at processing time that will
// always differ between pipelines (like UUIDs assigned to exception records)
const IGNORED_PATH_PATTERNS = [
    // Exception record IDs are generated during processing
    /^properties\.\$exception_list\[\d+\]\.id$/,
    /^properties\.\$exception_fingerprint_record\[\d+\]\.id$/,
]

// Arrays that should be compared as sets (order doesn't matter)
// Cymbal uses HashSet which has non-deterministic iteration order, so these
// arrays can have different ordering even within the same pipeline run
const UNORDERED_ARRAY_PATHS = new Set([
    'properties.$exception_types',
    'properties.$exception_values',
    'properties.$exception_sources',
    'properties.$exception_functions',
])

function shouldIgnorePath(path: string): boolean {
    return IGNORED_PATH_PATTERNS.some((pattern) => pattern.test(path))
}

function arraysEqualAsSet(a: unknown[], b: unknown[]): boolean {
    if (a.length !== b.length) {
        return false
    }
    const aSet = new Set(a.map((x) => JSON.stringify(x)))
    const bSet = new Set(b.map((x) => JSON.stringify(x)))
    if (aSet.size !== bSet.size) {
        return false
    }
    for (const item of aSet) {
        if (!bSet.has(item)) {
            return false
        }
    }
    return true
}

interface RawKafkaEvent {
    uuid: string
    event: string
    team_id: number
    distinct_id: string
    properties: string
    timestamp: string
    [key: string]: unknown
}

interface NormalizedEvent {
    uuid: string
    event: string
    team_id: number
    distinct_id: string
    properties: Record<string, unknown>
    timestamp: string
    [key: string]: unknown
}

interface CollectedEvent {
    raw: Message
    parsed: RawKafkaEvent
    normalized: NormalizedEvent
    receivedAt: number
}

interface ComparisonResult {
    uuid: string
    distinctId: string
    hasPersonInDb: boolean
    status: 'match' | 'mismatch' | 'missing_original' | 'missing_nodejs'
    original?: NormalizedEvent
    nodejs?: NormalizedEvent
    differences?: string[]
}

function parseArgs(): {
    duration: number
    originalTopic: string
    nodejsTopic: string
    brokers: string
} {
    const args = process.argv.slice(2)
    let duration = 30
    let originalTopic = 'clickhouse_events_json'
    let nodejsTopic = 'clickhouse_events_json_nodejs_test'
    let brokers = 'localhost:9092'

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--duration' && args[i + 1]) {
            duration = parseInt(args[i + 1], 10)
            i++
        } else if (args[i] === '--original-topic' && args[i + 1]) {
            originalTopic = args[i + 1]
            i++
        } else if (args[i] === '--nodejs-topic' && args[i + 1]) {
            nodejsTopic = args[i + 1]
            i++
        } else if (args[i] === '--brokers' && args[i + 1]) {
            brokers = args[i + 1]
            i++
        }
    }

    return { duration, originalTopic, nodejsTopic, brokers }
}

function createConsumer(brokers: string, groupId: string): KafkaConsumer {
    return new KafkaConsumer(
        {
            'group.id': groupId,
            'metadata.broker.list': brokers,
            'enable.auto.commit': false,
        },
        {
            'auto.offset.reset': 'latest',
        }
    )
}

async function collectEventsAfterReady(
    consumer: KafkaConsumer,
    durationMs: number
): Promise<Map<string, CollectedEvent>> {
    const events = new Map<string, CollectedEvent>()

    return new Promise((resolve, reject) => {
        consumer.on('data', (message: Message) => {
            try {
                if (!message.value) {
                    return
                }

                const parsed = parseJSON(message.value.toString()) as RawKafkaEvent

                // Only collect $exception events
                if (parsed.event !== '$exception') {
                    return
                }

                const normalized = normalizeEvent(parsed)

                events.set(parsed.uuid, {
                    raw: message,
                    parsed,
                    normalized,
                    receivedAt: Date.now(),
                })
            } catch (error) {
                // Skip malformed messages
            }
        })

        consumer.on('event.error', (err) => {
            console.error(`  ❌ Consumer error:`, err)
            reject(err)
        })

        consumer.consume()

        setTimeout(() => {
            consumer.disconnect()
            resolve(events)
        }, durationMs)
    })
}

function normalizeEvent(raw: RawKafkaEvent): NormalizedEvent {
    let properties: Record<string, unknown>
    if (typeof raw.properties === 'string') {
        try {
            properties = parseJSON(raw.properties) as Record<string, unknown>
        } catch {
            properties = { _parseError: true, _raw: raw.properties }
        }
    } else {
        properties = {}
    }

    return {
        ...raw,
        properties,
    }
}

/**
 * Normalize timestamps to ignore millisecond precision differences.
 * Cymbal includes milliseconds, Node drops them.
 */
function normalizeTimestamp(ts: string): string {
    // Remove milliseconds from timestamps like "2026-02-04 09:17:49.744"
    return ts.replace(/\.\d{3}$/, '')
}

/**
 * Compare JSON strings as objects to ignore key ordering differences.
 */
function jsonStringsEqual(a: string, b: string): boolean {
    try {
        const aObj = parseJSON(a)
        const bObj = parseJSON(b)
        // Deep compare the parsed objects
        return JSON.stringify(sortObjectKeys(aObj)) === JSON.stringify(sortObjectKeys(bObj))
    } catch {
        return a === b
    }
}

/**
 * Get differences between two JSON strings (for person_properties debugging).
 */
function getJsonDifferences(a: string, b: string): string[] {
    const differences: string[] = []
    try {
        const aObj = parseJSON(a) as Record<string, unknown>
        const bObj = parseJSON(b) as Record<string, unknown>
        const allKeys = new Set([...Object.keys(aObj), ...Object.keys(bObj)])

        for (const key of allKeys) {
            const aVal = aObj[key]
            const bVal = bObj[key]
            const aHas = key in aObj
            const bHas = key in bObj

            if (!aHas && bHas) {
                differences.push(`  + ${key}: ${JSON.stringify(bVal)}`)
            } else if (aHas && !bHas) {
                differences.push(`  - ${key}: ${JSON.stringify(aVal)}`)
            } else if (JSON.stringify(aVal) !== JSON.stringify(bVal)) {
                differences.push(`  ~ ${key}: ${JSON.stringify(aVal)} → ${JSON.stringify(bVal)}`)
            }
        }
    } catch {
        differences.push(`  (failed to parse JSON)`)
    }
    return differences
}

/**
 * Sort object keys recursively for consistent comparison.
 */
function sortObjectKeys(obj: unknown): unknown {
    if (obj === null || typeof obj !== 'object') {
        return obj
    }
    if (Array.isArray(obj)) {
        return obj.map(sortObjectKeys)
    }
    const sorted: Record<string, unknown> = {}
    for (const key of Object.keys(obj as Record<string, unknown>).sort()) {
        sorted[key] = sortObjectKeys((obj as Record<string, unknown>)[key])
    }
    return sorted
}

/**
 * Deep compare two values, with special handling for person fields based on distinct_id.
 */
function deepEqual(a: unknown, b: unknown, path: string, hasPersonInDb: boolean): string[] {
    const differences: string[] = []

    // Skip paths that match ignored patterns (e.g., dynamically generated IDs)
    if (shouldIgnorePath(path)) {
        return differences
    }

    if (a === b) {
        return differences
    }

    // Handle null/undefined equivalence
    const aIsEmpty = a === null || a === undefined
    const bIsEmpty = b === null || b === undefined
    if (aIsEmpty && bIsEmpty) {
        return differences
    }

    if (typeof a !== typeof b) {
        // Type mismatch - but allow if comparing empty values
        if (aIsEmpty || bIsEmpty) {
            return differences
        }
        differences.push(`${path}: type mismatch (${typeof a} vs ${typeof b})`)
        return differences
    }

    if (a === null || b === null) {
        if (a !== b) {
            differences.push(`${path}: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`)
        }
        return differences
    }

    if (Array.isArray(a) && Array.isArray(b)) {
        // For unordered arrays (like $exception_types), compare as sets
        // Cymbal uses HashSet which has non-deterministic iteration order
        if (UNORDERED_ARRAY_PATHS.has(path)) {
            if (!arraysEqualAsSet(a, b)) {
                differences.push(`${path}: set contents differ: [${a.join(', ')}] vs [${b.join(', ')}]`)
            }
            return differences
        }

        if (a.length !== b.length) {
            differences.push(`${path}: array length ${a.length} vs ${b.length}`)
        }
        const maxLen = Math.max(a.length, b.length)
        for (let i = 0; i < maxLen; i++) {
            differences.push(...deepEqual(a[i], b[i], `${path}[${i}]`, hasPersonInDb))
        }
        return differences
    }

    if (typeof a === 'object' && typeof b === 'object') {
        const aObj = a as Record<string, unknown>
        const bObj = b as Record<string, unknown>
        const allKeys = new Set([...Object.keys(aObj), ...Object.keys(bObj)])

        for (const key of allKeys) {
            // Skip always-ignored fields
            if (IGNORED_FIELDS.has(key)) {
                continue
            }

            const aVal = aObj[key]
            const bVal = bObj[key]
            const newPath = path ? `${path}.${key}` : key

            const aHasKey = key in aObj
            const bHasKey = key in bObj

            // Skip ignored property fields (Hog transformer additions not in Cymbal)
            // Only skip if missing in original (Cymbal) but present in nodejs
            if (path === 'properties' && IGNORED_PROPERTY_FIELDS.has(key)) {
                if (!aHasKey && bHasKey) {
                    // Expected: Node.js has it, Cymbal doesn't - skip this difference
                    continue
                }
                // If both have it or only Cymbal has it, still compare
            }

            // Special handling for person fields
            if (PERSON_FIELDS.has(key)) {
                if (hasPersonInDb) {
                    // Person exists - fields should match
                    if (!aHasKey && !bHasKey) {
                        continue
                    }
                    if (!aHasKey) {
                        differences.push(`${newPath}: missing in original (expected for person with db record)`)
                    } else if (!bHasKey) {
                        differences.push(`${newPath}: missing in nodejs (expected for person with db record)`)
                    } else {
                        // Special handling for person_properties (JSON string comparison)
                        if (key === 'person_properties' && typeof aVal === 'string' && typeof bVal === 'string') {
                            if (!jsonStringsEqual(aVal, bVal)) {
                                const jsonDiffs = getJsonDifferences(aVal, bVal)
                                differences.push(`${newPath}: JSON content differs`)
                                differences.push(...jsonDiffs.map((d) => `${newPath}${d}`))
                            }
                        } else if (
                            key === 'person_created_at' &&
                            typeof aVal === 'string' &&
                            typeof bVal === 'string'
                        ) {
                            // Special handling for person_created_at (timestamp comparison)
                            if (normalizeTimestamp(aVal) !== normalizeTimestamp(bVal)) {
                                differences.push(`${newPath}: ${aVal} vs ${bVal}`)
                            }
                        } else {
                            differences.push(...deepEqual(aVal, bVal, newPath, hasPersonInDb))
                        }
                    }
                } else {
                    // No person in db - Cymbal omits, Node has placeholder
                    // This is expected behavior, skip comparison
                    continue
                }
                continue
            }

            // Standard field comparison
            if (!aHasKey && !bHasKey) {
                continue
            }

            // Handle empty value equivalence
            const aIsEmptyVal = aVal === null || aVal === undefined || aVal === ''
            const bIsEmptyVal = bVal === null || bVal === undefined || bVal === ''
            if (!aHasKey && bIsEmptyVal) {
                continue
            }
            if (!bHasKey && aIsEmptyVal) {
                continue
            }

            if (!aHasKey) {
                differences.push(`${newPath}: missing in original`)
            } else if (!bHasKey) {
                differences.push(`${newPath}: missing in nodejs`)
            } else {
                differences.push(...deepEqual(aVal, bVal, newPath, hasPersonInDb))
            }
        }
        return differences
    }

    // Primitive comparison
    if (a !== b) {
        differences.push(`${path}: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`)
    }

    return differences
}

function compareEvents(
    originalEvents: Map<string, CollectedEvent>,
    nodejsEvents: Map<string, CollectedEvent>
): ComparisonResult[] {
    const results: ComparisonResult[] = []
    const allUuids = Array.from(new Set([...originalEvents.keys(), ...nodejsEvents.keys()]))

    for (const uuid of allUuids) {
        const original = originalEvents.get(uuid)
        const nodejs = nodejsEvents.get(uuid)
        const distinctId = original?.normalized.distinct_id || nodejs?.normalized.distinct_id || 'unknown'
        const hasPersonInDb = DISTINCT_IDS_WITH_PERSONS.has(distinctId)

        if (!original && nodejs) {
            results.push({
                uuid,
                distinctId,
                hasPersonInDb,
                status: 'missing_original',
                nodejs: nodejs.normalized,
            })
            continue
        }

        if (original && !nodejs) {
            results.push({
                uuid,
                distinctId,
                hasPersonInDb,
                status: 'missing_nodejs',
                original: original.normalized,
            })
            continue
        }

        if (original && nodejs) {
            const differences = deepEqual(original.normalized, nodejs.normalized, '', hasPersonInDb)

            results.push({
                uuid,
                distinctId,
                hasPersonInDb,
                status: differences.length > 0 ? 'mismatch' : 'match',
                original: original.normalized,
                nodejs: nodejs.normalized,
                differences: differences.length > 0 ? differences : undefined,
            })
        }
    }

    return results
}

function printReport(results: ComparisonResult[]): void {
    const matches = results.filter((r) => r.status === 'match')
    const mismatches = results.filter((r) => r.status === 'mismatch')
    const missingOriginal = results.filter((r) => r.status === 'missing_original')
    const missingNodejs = results.filter((r) => r.status === 'missing_nodejs')

    const withPerson = results.filter((r) => r.hasPersonInDb)
    const withoutPerson = results.filter((r) => !r.hasPersonInDb)

    console.log('')
    console.log('═══════════════════════════════════════════════════════════')
    console.log('                    COMPARISON REPORT')
    console.log('═══════════════════════════════════════════════════════════')
    console.log('')
    console.log(`  Total events compared: ${results.length}`)
    console.log(`  ✅ Matches:            ${matches.length}`)
    console.log(`  ❌ Mismatches:         ${mismatches.length}`)
    console.log(`  ⚠️  Missing original:   ${missingOriginal.length}`)
    console.log(`  ⚠️  Missing nodejs:     ${missingNodejs.length}`)
    console.log('')
    console.log(`  📋 Events with person in DB:    ${withPerson.length}`)
    console.log(`  📋 Events without person in DB: ${withoutPerson.length}`)
    console.log('')

    if (mismatches.length > 0) {
        console.log('───────────────────────────────────────────────────────────')
        console.log('MISMATCHES:')
        console.log('───────────────────────────────────────────────────────────')

        for (const mismatch of mismatches.slice(0, 10)) {
            console.log(`\n  UUID: ${mismatch.uuid}`)
            console.log(`  Distinct ID: ${mismatch.distinctId}`)
            console.log(`  Has person in DB: ${mismatch.hasPersonInDb}`)

            const origProps = mismatch.original?.properties as Record<string, unknown> | undefined
            const nodeProps = mismatch.nodejs?.properties as Record<string, unknown> | undefined
            console.log(`  Original fingerprint: ${origProps?.['$exception_fingerprint']}`)
            console.log(`  Nodejs fingerprint:   ${nodeProps?.['$exception_fingerprint']}`)

            console.log('  Differences:')
            for (const diff of mismatch.differences ?? []) {
                console.log(`    - ${diff}`)
            }
        }

        if (mismatches.length > 10) {
            console.log(`\n  ... and ${mismatches.length - 10} more mismatches`)
        }
    }

    if (missingOriginal.length > 0 && missingOriginal.length <= 5) {
        console.log('')
        console.log('───────────────────────────────────────────────────────────')
        console.log('MISSING FROM ORIGINAL (only in nodejs):')
        console.log('───────────────────────────────────────────────────────────')
        for (const missing of missingOriginal) {
            console.log(`  - ${missing.uuid} (distinct_id: ${missing.distinctId})`)
        }
    }

    if (missingNodejs.length > 0 && missingNodejs.length <= 5) {
        console.log('')
        console.log('───────────────────────────────────────────────────────────')
        console.log('MISSING FROM NODEJS (only in original):')
        console.log('───────────────────────────────────────────────────────────')
        for (const missing of missingNodejs) {
            console.log(`  - ${missing.uuid} (distinct_id: ${missing.distinctId})`)
        }
    }

    console.log('')
    console.log('═══════════════════════════════════════════════════════════')

    if (mismatches.length > 0) {
        process.exitCode = 1
    }
}

async function main(): Promise<void> {
    const { duration, originalTopic, nodejsTopic, brokers } = parseArgs()

    console.log('')
    console.log('🔬 Exception Pipeline Comparison Tool')
    console.log('─────────────────────────────────────')
    console.log(`  Duration:       ${duration} seconds`)
    console.log(`  Original topic: ${originalTopic}`)
    console.log(`  Nodejs topic:   ${nodejsTopic}`)
    console.log(`  Brokers:        ${brokers}`)
    console.log('')
    console.log(`  Known distinct_ids with persons: ${DISTINCT_IDS_WITH_PERSONS.size}`)
    console.log('')

    const timestamp = Date.now()
    const originalGroupId = `compare-original-${timestamp}`
    const nodejsGroupId = `compare-nodejs-${timestamp}`

    console.log('📡 Starting consumers...')

    const originalConsumer = createConsumer(brokers, originalGroupId)
    const nodejsConsumer = createConsumer(brokers, nodejsGroupId)

    const durationMs = duration * 1000

    console.log('\n⏳ Waiting for consumers to connect...')

    const originalReady = new Promise<void>((resolve) => {
        originalConsumer.on('ready', () => {
            console.log(`  ✅ Original topic consumer ready`)
            resolve()
        })
        originalConsumer.connect()
    })

    const nodejsReady = new Promise<void>((resolve) => {
        nodejsConsumer.on('ready', () => {
            console.log(`  ✅ Nodejs topic consumer ready`)
            resolve()
        })
        nodejsConsumer.connect()
    })

    await Promise.all([originalReady, nodejsReady])

    originalConsumer.subscribe([originalTopic])
    nodejsConsumer.subscribe([nodejsTopic])

    console.log(`\n🟢 READY - Collecting events for ${duration} seconds...`)
    console.log('   Send test exceptions now using send-test-exceptions.ts\n')

    const [originalEvents, nodejsEvents] = await Promise.all([
        collectEventsAfterReady(originalConsumer, durationMs),
        collectEventsAfterReady(nodejsConsumer, durationMs),
    ])

    console.log(`\n📊 Collection complete:`)
    console.log(`   Original topic: ${originalEvents.size} exception events`)
    console.log(`   Nodejs topic:   ${nodejsEvents.size} exception events`)

    const results = compareEvents(originalEvents, nodejsEvents)

    printReport(results)
}

main().catch((error) => {
    console.error('Fatal error:', error)
    process.exit(1)
})
