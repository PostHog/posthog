#!/usr/bin/env npx ts-node
/* eslint-disable no-restricted-globals */
/**
 * Test script to send sample $exception events to capture for testing the error tracking consumer.
 *
 * Events are generated with realistic variations to simulate production traffic:
 * - Person handling: known persons vs anonymous users
 * - Group analytics: $group_* properties (~30% of events)
 * - $set/$set_once: SDK-style person properties (~25% of events)
 * - Chained exceptions: multiple exceptions in $exception_list (~20% of events)
 * - Stacktrace variations: some exceptions without stacktraces (~10% of events)
 * - IP variations: real IPs or no IP
 * - SDK sources: posthog-js, posthog-node, posthog-python, etc.
 * - Minified filenames: production-style bundled JS paths (~15% of events)
 * - Unicode content: international characters in messages/functions (~10% of events)
 * - Long messages: very long error messages for truncation testing (~5% of events)
 * - Missing mechanism: exceptions without handled status (~10% of events)
 * - Error cases: empty exception list to test Cymbal error handling (with --include-errors)
 *
 * Usage:
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts
 *
 * Options:
 *   --count <n>       Number of events to send (default: 1)
 *   --delay <ms>      Delay between events in milliseconds (default: 0)
 *   --random-users    Use random distinct_ids (no persons in DB)
 *   --mixed           Alternate between known persons and random users
 *   --ip <address>    IP address to use for GeoIP lookup (sets X-Forwarded-For header)
 *                     Default: 89.160.20.129 (Swedish IP for consistent GeoIP results)
 *   --no-ip           Don't set X-Forwarded-For header (use socket IP)
 *   --randomize-ip    Randomize IP per event: 90% real, 10% none
 *   --include-errors  Include error cases (~5% empty exception lists)
 *
 * Examples:
 *   # Send 10 events using known persons (default)
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts --count 10
 *
 *   # Send 10 events with random distinct_ids (no person lookup expected)
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts --count 10 --random-users
 *
 *   # Send 20 events alternating between known and random users
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts --count 20 --mixed
 *
 *   # Send events with a specific IP for GeoIP testing
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts --count 5 --ip 8.8.8.8
 *
 *   # Comprehensive test with all variations including error cases
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts --count 100 --mixed --randomize-ip --include-errors
 */
import { randomUUID } from 'crypto'

const CAPTURE_URL = process.env.CAPTURE_URL || 'http://localhost:3307/e'
// Default token for local dev (team_id=1)
const TOKEN = process.env.POSTHOG_TOKEN || 'phc_placeholder'

// Distinct IDs that have real persons in the database (team_id=1)
// These are used to test person field handling in both pipelines
const DISTINCT_IDS_WITH_PERSONS = [
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
]

interface ExceptionFrame {
    filename: string
    lineno: number
    colno: number
    function: string
    in_app: boolean
}

interface ExceptionEntry {
    type: string
    value: string
    mechanism?: {
        type: string
        handled: boolean
    }
    stacktrace?: {
        frames: ExceptionFrame[]
    }
}

// Sample group types and IDs for testing group analytics
// These group types must already exist in the DB for team_id=1.
// Check with: SELECT group_type, group_type_index FROM posthog_grouptypemapping WHERE team_id = 1;
// Using existing types ensures both Cymbal and Node.js pipelines have cached mappings.
const GROUP_TYPES = ['account', 'instance', 'organization', 'project']
const GROUP_IDS = ['acme-corp', 'startup-inc', 'bigco-llc', 'project-alpha', 'org-123']

// Different SDK sources for realistic variation
const SDK_SOURCES = [
    { lib: 'posthog-js', version: '1.100.0' },
    { lib: 'posthog-node', version: '3.6.0' },
    { lib: 'posthog-python', version: '3.5.0' },
    { lib: 'posthog-ios', version: '3.2.0' },
    { lib: 'posthog-android', version: '3.1.0' },
    { lib: 'posthog-react-native', version: '2.10.0' },
    { lib: 'sentry-javascript', version: '7.100.0' }, // Sentry SDK via relay
]

// Minified/bundled filenames (realistic production JS)
const MINIFIED_FILES = [
    'https://app.example.com/static/js/main.a1b2c3d4.js',
    'https://cdn.example.com/bundle.min.js',
    'webpack:///src/components/Dashboard.tsx',
    'app:///src/utils/helpers.ts',
    '/assets/vendor.chunk.abc123.js',
]

// Unicode and special character examples
const UNICODE_MESSAGES = [
    '無効な入力です (Invalid input)', // Japanese
    'Ошибка подключения к базе данных', // Russian
    'Échec de la connexion réseau', // French
    '数据库连接失败 🔥', // Chinese with emoji
    'Ungültiger Wert für Feld "größe"', // German with special chars
    "Error in function 'calculate_tötäl'", // Mixed
    'Stack overflow in λ expression', // Greek letter
    'Null pointer: obj→field→value', // Arrow symbols
]

const UNICODE_FUNCTIONS = [
    'handleSubmitForm_日本語',
    'проверитьДанные',
    'vérifierConnexion',
    '处理请求',
    'größeBerechnen',
    'λCalculate',
]

function generateStackTrace(useMinified: boolean = false): ExceptionFrame[] {
    const normalFiles = [
        'src/components/Dashboard.tsx',
        'src/hooks/useData.ts',
        'src/api/client.ts',
        'src/utils/helpers.ts',
        'node_modules/axios/lib/core/dispatchRequest.js',
    ]

    const files = useMinified ? MINIFIED_FILES : normalFiles

    const normalFunctions = ['Dashboard', 'useEffect', 'fetchData', 'handleResponse', 'processError', 'dispatchRequest']
    // 10% chance of unicode function names
    const functions = Math.random() < 0.1 ? UNICODE_FUNCTIONS : normalFunctions

    const frameCount = Math.floor(Math.random() * 5) + 3
    const frames: ExceptionFrame[] = []

    for (let i = 0; i < frameCount; i++) {
        frames.push({
            filename: files[Math.floor(Math.random() * files.length)],
            lineno: Math.floor(Math.random() * 500) + 1,
            colno: Math.floor(Math.random() * 100) + 1,
            function: functions[Math.floor(Math.random() * functions.length)],
            in_app: !files[i]?.includes('node_modules') && !files[i]?.includes('vendor'),
        })
    }

    return frames
}

// Generate a very long message to test truncation (Cymbal truncates at 10,000 chars)
function generateLongMessage(): string {
    const base = 'This is a very long error message that repeats to test truncation behavior. '
    const targetLength = 12000 // Over the 10,000 char limit
    let message = ''
    while (message.length < targetLength) {
        message += base
    }
    return message + ' [END]'
}

function generateException(
    options: {
        includeStacktrace?: boolean
        useMinified?: boolean
        useLongMessage?: boolean
        useUnicode?: boolean
        includeMechanism?: boolean
    } = {}
): ExceptionEntry {
    const {
        includeStacktrace = true,
        useMinified = false,
        useLongMessage = false,
        useUnicode = false,
        includeMechanism = true,
    } = options

    const errorTypes = [
        {
            type: 'TypeError',
            messages: [
                'Cannot read property of undefined',
                "Cannot read properties of null (reading 'map')",
                'x is not a function',
            ],
        },
        { type: 'ReferenceError', messages: ['x is not defined', 'Cannot access before initialization'] },
        { type: 'SyntaxError', messages: ['Unexpected token', 'Invalid or unexpected token'] },
        { type: 'Error', messages: ['Network request failed', 'Request timeout', 'Invalid response format'] },
        { type: 'RangeError', messages: ['Maximum call stack size exceeded', 'Invalid array length'] },
    ]

    const errorType = errorTypes[Math.floor(Math.random() * errorTypes.length)]

    let message: string
    if (useLongMessage) {
        message = generateLongMessage()
    } else if (useUnicode) {
        message = UNICODE_MESSAGES[Math.floor(Math.random() * UNICODE_MESSAGES.length)]
    } else {
        message = errorType.messages[Math.floor(Math.random() * errorType.messages.length)]
    }

    const exception: ExceptionEntry = {
        type: errorType.type,
        value: message,
    }

    // 90% include mechanism, 10% omit it (tests missing optional field)
    if (includeMechanism) {
        exception.mechanism = {
            type: 'generic',
            handled: Math.random() > 0.3,
        }
    }

    if (includeStacktrace) {
        exception.stacktrace = { frames: generateStackTrace(useMinified) }
    }

    return exception
}

interface ExceptionListOptions {
    forceEmpty?: boolean // Generate empty list (Cymbal error case)
    forceLongMessage?: boolean // Generate very long message (truncation test)
}

interface ExceptionListResult {
    list: ExceptionEntry[]
    hasMinified: boolean
    hasUnicode: boolean
    hasLongMessage: boolean
    hasMissingMechanism: boolean
    isEmpty: boolean
}

function generateExceptionList(options: ExceptionListOptions = {}): ExceptionListResult {
    // Empty exception list - triggers Cymbal error
    if (options.forceEmpty) {
        return {
            list: [],
            hasMinified: false,
            hasUnicode: false,
            hasLongMessage: false,
            hasMissingMechanism: false,
            isEmpty: true,
        }
    }

    // 80% single exception, 20% chained exceptions (2-3)
    const count = Math.random() < 0.8 ? 1 : Math.floor(Math.random() * 2) + 2
    // 10% chance of no stacktrace on primary exception
    const includeStacktrace = Math.random() > 0.1
    // 15% chance of minified/bundled filenames
    const useMinified = Math.random() < 0.15
    // 10% chance of unicode in messages
    const useUnicode = Math.random() < 0.1
    // 5% chance of very long message (or forced)
    const useLongMessage = options.forceLongMessage || Math.random() < 0.05
    // 10% chance of missing mechanism on primary exception
    const includeMechanism = Math.random() > 0.1

    const exceptions: ExceptionEntry[] = []
    for (let i = 0; i < count; i++) {
        // Chained exceptions (cause) often don't have stacktraces
        const hasStack = i === 0 ? includeStacktrace : Math.random() > 0.5
        exceptions.push(
            generateException({
                includeStacktrace: hasStack,
                useMinified,
                useLongMessage: i === 0 && useLongMessage, // Only primary gets long message
                useUnicode: i === 0 && useUnicode, // Only primary gets unicode
                includeMechanism: i === 0 ? includeMechanism : true,
            })
        )
    }

    return {
        list: exceptions,
        hasMinified: useMinified,
        hasUnicode: useUnicode,
        hasLongMessage: useLongMessage,
        hasMissingMechanism: !includeMechanism,
        isEmpty: false,
    }
}

function generateGroupProperties(): Record<string, unknown> {
    // 30% chance of having group properties
    if (Math.random() > 0.3) {
        return {}
    }

    const groupCount = Math.floor(Math.random() * 2) + 1 // 1-2 groups

    // Real SDKs only send $groups with type names - the backend maps these
    // to $group_<index> based on the team's group type configuration.
    // We don't add $group_* directly here.
    const groups: Record<string, string> = {}
    for (let i = 0; i < groupCount; i++) {
        const groupType = GROUP_TYPES[i % GROUP_TYPES.length]
        const groupId = GROUP_IDS[Math.floor(Math.random() * GROUP_IDS.length)]
        groups[groupType] = groupId
    }

    return { $groups: groups }
}

function generateSetProperties(): { $set?: Record<string, unknown>; $set_once?: Record<string, unknown> } {
    // 25% chance of having $set properties (simulating SDK-added properties)
    // Note: In production, Hog transformer adds GeoIP data to $set. We test with
    // sample data to verify both pipelines handle pre-existing $set correctly.
    if (Math.random() > 0.25) {
        return {}
    }

    const props: { $set?: Record<string, unknown>; $set_once?: Record<string, unknown> } = {}

    // $set properties (like GeoIP data that Hog transformer adds)
    if (Math.random() > 0.3) {
        props.$set = {
            $browser: 'Chrome',
            $os: 'Mac OS X',
            // Simulate GeoIP-like data
            $geoip_country_name: 'Sweden',
            $geoip_city_name: 'Linköping',
        }
    }

    // $set_once properties
    if (Math.random() > 0.5) {
        props.$set_once = {
            $initial_referrer: 'https://google.com',
            $initial_utm_source: 'organic',
        }
    }

    return props
}

interface EventVariations {
    hasGroups: boolean
    hasSetProps: boolean
    exceptionCount: number
    hasStacktrace: boolean
    ipType: 'real' | 'none'
    sdk: string
    hasMinified: boolean
    hasUnicode: boolean
    hasLongMessage: boolean
    hasMissingMechanism: boolean
    isEmptyExceptionList: boolean
}

// Default IP for GeoIP testing - Swedish IP (same as Hog transformer uses for local dev spoofing)
const DEFAULT_TEST_IP = '89.160.20.129'

// Additional real IPs for variety in GeoIP results
const REAL_IPS = [
    '89.160.20.129', // Sweden (Linköping)
    '8.8.8.8', // USA (Google DNS)
    '1.1.1.1', // Australia (Cloudflare)
    '208.67.222.222', // USA (OpenDNS)
]

function selectIp(randomizeIp: boolean, explicitIp?: string): { ip: string | undefined; ipType: 'real' | 'none' } {
    if (explicitIp !== undefined) {
        // Explicit IP provided via --ip flag (or --no-ip sets it to empty string)
        if (explicitIp === '') {
            return { ip: undefined, ipType: 'none' }
        }
        return { ip: explicitIp, ipType: 'real' }
    }

    if (!randomizeIp) {
        return { ip: DEFAULT_TEST_IP, ipType: 'real' }
    }

    // Randomize: 90% real IP, 10% no IP
    // Note: We don't test private IPs because Hog transformer spoofs them to real IPs,
    // but Cymbal doesn't, leading to expected GeoIP differences that aren't useful to test.
    if (Math.random() < 0.9) {
        return { ip: REAL_IPS[Math.floor(Math.random() * REAL_IPS.length)], ipType: 'real' }
    } else {
        return { ip: undefined, ipType: 'none' }
    }
}

async function sendException(
    distinctId: string,
    options: {
        randomizeIp: boolean
        explicitIp?: string
        forceEmptyExceptionList?: boolean
        forceLongMessage?: boolean
    }
): Promise<EventVariations> {
    const eventUuid = randomUUID()

    // Generate exception list with possible variations
    const exceptionResult = generateExceptionList({
        forceEmpty: options.forceEmptyExceptionList,
        forceLongMessage: options.forceLongMessage,
    })

    // Generate optional group and $set properties
    const groupProps = generateGroupProperties()
    const setProps = generateSetProperties()

    // Select IP for this event
    const { ip, ipType } = selectIp(options.randomizeIp, options.explicitIp)

    // Randomize SDK source
    const sdk = SDK_SOURCES[Math.floor(Math.random() * SDK_SOURCES.length)]

    const event = {
        token: TOKEN,
        distinct_id: distinctId,
        event: '$exception',
        properties: {
            $exception_list: exceptionResult.list,
            $current_url: 'http://localhost:3000/dashboard',
            $browser: 'Chrome',
            $browser_version: '120.0.0',
            $os: 'Mac OS X',
            $device_type: 'Desktop',
            $lib: sdk.lib,
            $lib_version: sdk.version,
            ...groupProps,
            ...setProps,
        },
        uuid: eventUuid,
        timestamp: new Date().toISOString(),
    }

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
    }

    // Set X-Forwarded-For to simulate a real client IP for GeoIP lookup
    if (ip) {
        headers['X-Forwarded-For'] = ip
    }

    const response = await fetch(CAPTURE_URL, {
        method: 'POST',
        headers,
        body: JSON.stringify(event),
    })

    if (!response.ok) {
        throw new Error(`Capture returned ${response.status}: ${await response.text()}`)
    }

    // Track variations for logging
    const variations: EventVariations = {
        hasGroups: Object.keys(groupProps).length > 0,
        hasSetProps: '$set' in setProps || '$set_once' in setProps,
        exceptionCount: exceptionResult.list.length,
        hasStacktrace: exceptionResult.list[0]?.stacktrace !== undefined,
        ipType,
        sdk: sdk.lib,
        hasMinified: exceptionResult.hasMinified,
        hasUnicode: exceptionResult.hasUnicode,
        hasLongMessage: exceptionResult.hasLongMessage,
        hasMissingMechanism: exceptionResult.hasMissingMechanism,
        isEmptyExceptionList: exceptionResult.isEmpty,
    }

    // Build variation indicators
    const indicators: string[] = []
    const hasPersonInDb = DISTINCT_IDS_WITH_PERSONS.includes(distinctId)
    indicators.push(hasPersonInDb ? '👤' : '👻') // person status
    if (variations.hasGroups) {
        indicators.push('👥')
    } // groups
    if (variations.hasSetProps) {
        indicators.push('📝')
    } // $set props
    if (variations.exceptionCount > 1) {
        indicators.push(`⛓${variations.exceptionCount}`)
    } // chained
    if (!variations.hasStacktrace && !variations.isEmptyExceptionList) {
        indicators.push('📭')
    } // no stacktrace
    if (variations.ipType === 'none') {
        indicators.push('❌')
    } // no IP
    if (variations.hasMinified) {
        indicators.push('📦')
    } // minified
    if (variations.hasUnicode) {
        indicators.push('🌐')
    } // unicode
    if (variations.hasLongMessage) {
        indicators.push('📜')
    } // long message
    if (variations.hasMissingMechanism) {
        indicators.push('❓')
    } // missing mechanism
    if (variations.isEmptyExceptionList) {
        indicators.push('⚠️')
    } // empty list (error case)

    const exceptionType = exceptionResult.list[0]?.type ?? '(empty)'
    console.log(
        `✅ ${indicators.join('')} ${eventUuid.substring(0, 8)}… | ${distinctId.substring(0, 16).padEnd(16)} | ${exceptionType} | ${sdk.lib}`
    )

    return variations
}

function getDistinctId(index: number, useKnownPersons: boolean): string {
    if (useKnownPersons) {
        // Cycle through known distinct_ids that have persons in the database
        return DISTINCT_IDS_WITH_PERSONS[index % DISTINCT_IDS_WITH_PERSONS.length]
    } else {
        // Generate random distinct_id (no person in database)
        return `test-user-${randomUUID().substring(0, 8)}`
    }
}

async function main(): Promise<void> {
    const args = process.argv.slice(2)
    let count = 1
    let delay = 0
    let useKnownPersons = true // Default to using known persons
    let explicitIp: string | undefined = undefined // undefined means use default behavior
    let randomizeIp = false
    let includeErrors = false // Include error cases (empty exception list, etc.)

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--count' && args[i + 1]) {
            count = parseInt(args[i + 1], 10)
            i++
        } else if (args[i] === '--delay' && args[i + 1]) {
            delay = parseInt(args[i + 1], 10)
            i++
        } else if (args[i] === '--random-users') {
            useKnownPersons = false
        } else if (args[i] === '--mixed') {
            // Will be handled per-event below
            useKnownPersons = true
        } else if (args[i] === '--ip' && args[i + 1]) {
            explicitIp = args[i + 1]
            i++
        } else if (args[i] === '--no-ip') {
            explicitIp = '' // Empty string signals no IP
        } else if (args[i] === '--randomize-ip') {
            randomizeIp = true
        } else if (args[i] === '--include-errors') {
            includeErrors = true
        }
    }

    const mixedMode = args.includes('--mixed')

    console.log(`🚀 Sending ${count} exception event(s) to ${CAPTURE_URL}`)
    console.log(`   Token: ${TOKEN}`)
    if (mixedMode) {
        console.log(`   Mode: mixed (alternating known persons and random users)`)
    } else if (useKnownPersons) {
        console.log(`   Mode: known persons (distinct_ids with persons in DB)`)
    } else {
        console.log(`   Mode: random users (no persons in DB)`)
    }
    if (explicitIp !== undefined) {
        if (explicitIp === '') {
            console.log(`   IP: none (using socket IP)`)
        } else {
            console.log(`   IP: ${explicitIp} (X-Forwarded-For)`)
        }
    } else if (randomizeIp) {
        console.log(`   IP: randomized (90% real, 10% none)`)
    } else {
        console.log(`   IP: ${DEFAULT_TEST_IP} (default Swedish IP)`)
    }
    if (includeErrors) {
        console.log(`   Errors: including error cases (empty exception list, etc.)`)
    }
    if (delay > 0) {
        console.log(`   Delay: ${delay}ms between events`)
    }
    console.log('')
    console.log('Legend: 👤=person 👻=no-person 👥=groups 📝=$set ⛓=chained 📭=no-stack ❌=no-ip')
    console.log('        📦=minified 🌐=unicode 📜=long-msg ❓=no-mechanism ⚠️=error-case')
    console.log('')

    // Track variation stats
    const stats = {
        withPerson: 0,
        withGroups: 0,
        withSetProps: 0,
        chainedExceptions: 0,
        noStacktrace: 0,
        noIp: 0,
        minified: 0,
        unicode: 0,
        longMessage: 0,
        missingMechanism: 0,
        errorCases: 0,
        total: 0,
        sdkCounts: {} as Record<string, number>,
    }

    for (let i = 0; i < count; i++) {
        try {
            // In mixed mode, alternate between known persons and random users
            const useKnown = mixedMode ? i % 2 === 0 : useKnownPersons
            const distinctId = getDistinctId(i, useKnown)

            // Occasionally force error cases if --include-errors is set
            // ~5% empty exception list when errors enabled
            const forceEmptyExceptionList = includeErrors && Math.random() < 0.05

            const variations = await sendException(distinctId, {
                randomizeIp,
                explicitIp,
                forceEmptyExceptionList,
            })

            // Update stats
            stats.total++
            if (DISTINCT_IDS_WITH_PERSONS.includes(distinctId)) {
                stats.withPerson++
            }
            if (variations.hasGroups) {
                stats.withGroups++
            }
            if (variations.hasSetProps) {
                stats.withSetProps++
            }
            if (variations.exceptionCount > 1) {
                stats.chainedExceptions++
            }
            if (!variations.hasStacktrace && !variations.isEmptyExceptionList) {
                stats.noStacktrace++
            }
            if (variations.ipType === 'none') {
                stats.noIp++
            }
            if (variations.hasMinified) {
                stats.minified++
            }
            if (variations.hasUnicode) {
                stats.unicode++
            }
            if (variations.hasLongMessage) {
                stats.longMessage++
            }
            if (variations.hasMissingMechanism) {
                stats.missingMechanism++
            }
            if (variations.isEmptyExceptionList) {
                stats.errorCases++
            }
            stats.sdkCounts[variations.sdk] = (stats.sdkCounts[variations.sdk] || 0) + 1

            if (delay > 0 && i < count - 1) {
                await new Promise((resolve) => setTimeout(resolve, delay))
            }
        } catch (error) {
            console.error(`❌ Failed to send event: ${error}`)
        }
    }

    console.log('')
    console.log('📊 Summary:')
    console.log(`   Total events: ${stats.total}`)
    console.log(`   With person: ${stats.withPerson} (${pct(stats.withPerson, stats.total)})`)
    console.log(`   With groups: ${stats.withGroups} (${pct(stats.withGroups, stats.total)})`)
    console.log(`   With $set/$set_once: ${stats.withSetProps} (${pct(stats.withSetProps, stats.total)})`)
    console.log(`   Chained exceptions: ${stats.chainedExceptions} (${pct(stats.chainedExceptions, stats.total)})`)
    console.log(`   No stacktrace: ${stats.noStacktrace} (${pct(stats.noStacktrace, stats.total)})`)
    if (randomizeIp || explicitIp === undefined) {
        console.log(`   No IP: ${stats.noIp} (${pct(stats.noIp, stats.total)})`)
    }
    console.log(`   Minified frames: ${stats.minified} (${pct(stats.minified, stats.total)})`)
    console.log(`   Unicode content: ${stats.unicode} (${pct(stats.unicode, stats.total)})`)
    console.log(`   Long messages: ${stats.longMessage} (${pct(stats.longMessage, stats.total)})`)
    console.log(`   Missing mechanism: ${stats.missingMechanism} (${pct(stats.missingMechanism, stats.total)})`)
    if (includeErrors) {
        console.log(`   Error cases: ${stats.errorCases} (${pct(stats.errorCases, stats.total)})`)
    }
    console.log('')
    console.log('📱 SDK Distribution:')
    for (const [sdk, sdkCount] of Object.entries(stats.sdkCounts).sort((a, b) => b[1] - a[1])) {
        console.log(`   ${sdk}: ${sdkCount} (${pct(sdkCount, stats.total)})`)
    }
    console.log('')
    console.log('✨ Done!')
}

function pct(value: number, total: number): string {
    if (total === 0) {
        return '0%'
    }
    return `${Math.round((value / total) * 100)}%`
}

main().catch(console.error)
/* eslint-enable no-restricted-globals */
