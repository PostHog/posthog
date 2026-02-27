#!/usr/bin/env npx ts-node
/* eslint-disable no-restricted-globals */
/**
 * Test script to send sample $exception events to capture for testing the error tracking consumer.
 *
 * Usage:
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts
 *
 * Options:
 *   --count <n>      Number of events to send (default: 1)
 *   --delay <ms>     Delay between events in milliseconds (default: 0)
 *   --random-users   Use random distinct_ids (no persons in DB)
 *   --mixed          Alternate between known persons and random users
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

function generateStackTrace(): ExceptionFrame[] {
    const files = [
        'src/components/Dashboard.tsx',
        'src/hooks/useData.ts',
        'src/api/client.ts',
        'src/utils/helpers.ts',
        'node_modules/axios/lib/core/dispatchRequest.js',
    ]

    const functions = ['Dashboard', 'useEffect', 'fetchData', 'handleResponse', 'processError', 'dispatchRequest']

    const frameCount = Math.floor(Math.random() * 5) + 3
    const frames: ExceptionFrame[] = []

    for (let i = 0; i < frameCount; i++) {
        frames.push({
            filename: files[Math.floor(Math.random() * files.length)],
            lineno: Math.floor(Math.random() * 500) + 1,
            colno: Math.floor(Math.random() * 100) + 1,
            function: functions[Math.floor(Math.random() * functions.length)],
            in_app: !files[i]?.includes('node_modules'),
        })
    }

    return frames
}

function generateException(): ExceptionEntry {
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
    const message = errorType.messages[Math.floor(Math.random() * errorType.messages.length)]

    return {
        type: errorType.type,
        value: message,
        mechanism: {
            type: 'generic',
            handled: Math.random() > 0.3,
        },
        stacktrace: {
            frames: generateStackTrace(),
        },
    }
}

async function sendException(distinctId: string): Promise<void> {
    const eventUuid = randomUUID()

    const event = {
        token: TOKEN,
        distinct_id: distinctId,
        event: '$exception',
        properties: {
            $exception_list: [generateException()],
            $current_url: 'http://localhost:3000/dashboard',
            $browser: 'Chrome',
            $browser_version: '120.0.0',
            $os: 'Mac OS X',
            $device_type: 'Desktop',
            $lib: 'posthog-js',
            $lib_version: '1.100.0',
        },
        uuid: eventUuid,
        timestamp: new Date().toISOString(),
    }

    const response = await fetch(CAPTURE_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(event),
    })

    if (!response.ok) {
        throw new Error(`Capture returned ${response.status}: ${await response.text()}`)
    }

    const hasPersonInDb = DISTINCT_IDS_WITH_PERSONS.includes(distinctId)
    const personIndicator = hasPersonInDb ? '👤' : '👻'
    console.log(
        `✅ ${personIndicator} Sent: ${eventUuid.substring(0, 8)}… | ${distinctId.substring(0, 20).padEnd(20)} | ${event.properties.$exception_list[0].type}`
    )
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
    if (delay > 0) {
        console.log(`   Delay: ${delay}ms between events`)
    }
    console.log('')

    for (let i = 0; i < count; i++) {
        try {
            // In mixed mode, alternate between known persons and random users
            const useKnown = mixedMode ? i % 2 === 0 : useKnownPersons
            const distinctId = getDistinctId(i, useKnown)
            await sendException(distinctId)
            if (delay > 0 && i < count - 1) {
                await new Promise((resolve) => setTimeout(resolve, delay))
            }
        } catch (error) {
            console.error(`❌ Failed to send event: ${error}`)
        }
    }

    console.log('')
    console.log('✨ Done!')
}

main().catch(console.error)
/* eslint-enable no-restricted-globals */
