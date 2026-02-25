/**
 * Test event data helpers for Playwright tests.
 *
 * Seed events into a workspace so your tests have data to query against.
 * Pass the events array to createWorkspace({ events }) and the backend
 * will create persons and ingest events automatically.
 *
 * Basic usage:
 *   createEvent()                          // alice does a pageview now
 *   createEvent({ user: users.bob })       // bob does a pageview now
 *   createEvent({ timestamp: daysAgo(3) }) // alice does a pageview 3 days ago
 *
 * Multiple events:
 *   createEvent().repeat(10)                                  // 10 identical pageviews from alice
 *   createEvent({ user: (n) => `user-${n}` }).repeat(10)     // 10 different users, one pageview each
 *
 * Combining events for a test:
 *   const events = [
 *       ...createEvent({ user: (n) => `user-${n}`, timestamp: daysAgo(0) }).repeat(10),
 *       ...createEvent({ user: (n) => `user-${n}`, timestamp: daysAgo(1) }).repeat(8),
 *   ]
 */

import { PlaywrightSetupEvent } from './playwright-setup'

// --- Constants ---

export const users = {
    alice: 'alice',
    bob: 'bob',
} as const

export const eventNames = {
    pageview: '$pageview',
    autocapture: '$autocapture',
} as const

const defaultProperties: Record<string, any> = {
    $browser: 'Chrome',
    $os: 'Mac OS X',
    $current_url: 'https://posthog.com',
}

// --- Timestamp helpers ---

export function daysAgo(days: number): string {
    const date = new Date()
    date.setDate(date.getDate() - days)
    return date.toISOString()
}

export function hoursAgo(hours: number): string {
    const date = new Date()
    date.setHours(date.getHours() - hours)
    return date.toISOString()
}

// --- Event creation ---

type ValueOrFn<T> = T | ((n: number) => T)

interface CreateEventOptions {
    event?: string
    user?: ValueOrFn<string>
    timestamp?: ValueOrFn<string>
    properties?: Record<string, any>
}

interface RepeatOptions {
    randomizeTimes?: boolean
    randomizeDays?: number
}

interface EventResult {
    events: PlaywrightSetupEvent[]
    repeat(count: number, options?: RepeatOptions): PlaywrightSetupEvent[]
}

function resolve<T>(value: ValueOrFn<T>, n: number): T {
    return typeof value === 'function' ? (value as (n: number) => T)(n) : value
}

function toEvent(options: CreateEventOptions, n: number): PlaywrightSetupEvent {
    const timestamp = options.timestamp ? resolve(options.timestamp, n) : new Date().toISOString()

    return {
        event: options.event ?? eventNames.pageview,
        distinct_id: resolve(options.user ?? users.alice, n),
        timestamp,
        properties: { ...defaultProperties, ...options.properties },
    }
}

export function createEvent(options: CreateEventOptions = {}): EventResult {
    const single = toEvent(options, 0)

    return {
        events: [single],
        repeat(count: number, repeatOptions: RepeatOptions = {}): PlaywrightSetupEvent[] {
            return Array.from({ length: count }, (_, n) => {
                const event = toEvent(options, n)

                if (repeatOptions.randomizeTimes) {
                    const date = new Date(event.timestamp)
                    date.setHours(date.getHours() - Math.floor(Math.random() * 24))
                    event.timestamp = date.toISOString()
                }

                if (repeatOptions.randomizeDays != null) {
                    const date = new Date(event.timestamp)
                    date.setDate(date.getDate() - Math.floor(Math.random() * repeatOptions.randomizeDays))
                    event.timestamp = date.toISOString()
                }

                return event
            })
        },
    }
}
