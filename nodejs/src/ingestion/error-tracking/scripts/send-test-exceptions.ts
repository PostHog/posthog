#!/usr/bin/env npx ts-node
/* eslint-disable no-restricted-globals */
/**
 * Test script to send sample $exception events to capture for testing the error tracking consumer.
 *
 * Usage:
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts
 *
 * Or with options:
 *   npx ts-node src/ingestion/error-tracking/scripts/send-test-exceptions.ts --count 10 --delay 500
 */
import { randomUUID } from 'crypto'

const CAPTURE_URL = process.env.CAPTURE_URL || 'http://localhost:3307/e'
const TOKEN = process.env.POSTHOG_TOKEN || 'phc_local' // phc_local works in dev for team 1

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

async function sendException(): Promise<void> {
    const eventUuid = randomUUID()
    const distinctId = `test-user-${Math.floor(Math.random() * 100)}`

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

    console.log(
        `✅ Sent exception event: ${eventUuid} (${event.properties.$exception_list[0].type}: ${event.properties.$exception_list[0].value})`
    )
}

async function main(): Promise<void> {
    const args = process.argv.slice(2)
    let count = 1
    let delay = 0

    for (let i = 0; i < args.length; i++) {
        if (args[i] === '--count' && args[i + 1]) {
            count = parseInt(args[i + 1], 10)
            i++
        } else if (args[i] === '--delay' && args[i + 1]) {
            delay = parseInt(args[i + 1], 10)
            i++
        }
    }

    console.log(`🚀 Sending ${count} exception event(s) to ${CAPTURE_URL}`)
    console.log(`   Token: ${TOKEN}`)
    if (delay > 0) {
        console.log(`   Delay: ${delay}ms between events`)
    }
    console.log('')

    for (let i = 0; i < count; i++) {
        try {
            await sendException()
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
