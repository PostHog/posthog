/**
 * Shared test datasets for Playwright tests.
 *
 * Each dataset bundles events with their expected values so tests can
 * import exactly the data they need without duplicating event definitions
 * or recalculating expected totals.
 *
 * Usage:
 *   import { pageviews, customEventsWithBreakdown } from '../../utils/test-data'
 *
 *   const events = [...pageviews.events, ...customEventsWithBreakdown.events]
 *   // then pass to createWorkspace({ events })
 *   // and assert with e.g. pageviews.expected.total
 */

import { createEvent, daysAgo, hoursAgo } from './event-data'

const pvUser = (n: number): string => `pv-user-${n}`
const customUser = (n: number): string => `custom-user-${n}`

/**
 * Two persons with known identities and person properties (via $set).
 * - alice@example.com: 2 pageviews, person props name=Alice, plan=pro
 * - customer-42: 1 pageview, person props name=Bob, plan=free
 */
export const personsWithIdentity = {
    events: [
        ...createEvent({
            event: '$pageview',
            user: () => 'alice@example.com',
            timestamp: hoursAgo(2),
            properties: { $set: { name: 'Alice', plan: 'pro' } },
        }).repeat(2),
        ...createEvent({
            event: '$pageview',
            user: () => 'customer-42',
            timestamp: hoursAgo(4),
            properties: { $set: { name: 'Bob', plan: 'free' } },
        }).repeat(1),
    ],
    expected: {
        emailUser: 'alice@example.com',
        customIdUser: 'customer-42',
    },
}

/**
 * A person with two distinct IDs and one pageview.
 * Used to test the "Split IDs" button on the person detail page.
 */
export const personWithMultipleIds = {
    person: {
        distinct_ids: ['charlie@example.com', 'anon-charlie-123'],
        properties: { name: 'Charlie', plan: 'enterprise' },
    },
    events: [
        ...createEvent({
            event: '$pageview',
            user: () => 'charlie@example.com',
            timestamp: hoursAgo(1),
        }).repeat(1),
    ],
    expected: {
        primaryDistinctId: 'charlie@example.com',
        displayName: 'Charlie',
    },
}

/**
 * 7-day descending pageview pattern: 10, 8, 6, 5, 4, 3, 2 = 38 total.
 * Each day uses distinct users (pv-user-0 through pv-user-N).
 */
export const pageviews = {
    eventName: '$pageview',
    events: [
        ...createEvent({ event: '$pageview', user: pvUser, timestamp: daysAgo(6) }).repeat(10),
        ...createEvent({ event: '$pageview', user: pvUser, timestamp: daysAgo(5) }).repeat(8),
        ...createEvent({ event: '$pageview', user: pvUser, timestamp: daysAgo(4) }).repeat(6),
        ...createEvent({ event: '$pageview', user: pvUser, timestamp: daysAgo(3) }).repeat(5),
        ...createEvent({ event: '$pageview', user: pvUser, timestamp: daysAgo(2) }).repeat(4),
        ...createEvent({ event: '$pageview', user: pvUser, timestamp: hoursAgo(36) }).repeat(3),
        ...createEvent({ event: '$pageview', user: pvUser, timestamp: daysAgo(0) }).repeat(2),
    ],
    expected: {
        total: '38',
    },
}

/**
 * Custom events split across two browsers with positive/negative amounts.
 * - Chrome: 5 events with amount=10 each (sum=50)
 * - Firefox: 3 events with amount=-5 each (sum=-15)
 * Users overlap: custom-user-0..4 for Chrome, custom-user-0..2 for Firefox,
 * so unique users = 5.
 */
export const customEventsWithBreakdown = {
    eventName: 'custom_test_event',
    events: [
        ...createEvent({
            event: 'custom_test_event',
            user: customUser,
            timestamp: daysAgo(3),
            properties: { $browser: 'Chrome', amount: 10 },
        }).repeat(5),
        ...createEvent({
            event: 'custom_test_event',
            user: customUser,
            timestamp: daysAgo(2),
            properties: { $browser: 'Firefox', amount: -5 },
        }).repeat(3),
    ],
    expected: {
        total: '8',
        uniqueUsers: '5',
        chromeCount: '5',
        firefoxCount: '3',
        amountSum: '35',
        chromeAmountSum: '50',
        firefoxAmountSum: '-15',
    },
}
/**
 * Stickiness-specific pageview data: 10 users with known day-activity patterns.
 *
 * - 1 "power user" (sticky-power-0): active on 5 distinct days → Day 5 bucket
 * - 3 "regular users" (sticky-regular-0..2): active on 3 distinct days → Day 3 bucket
 * - 6 "casual users" (sticky-casual-0..5): active on 1 day only → Day 1 bucket
 *
 * Expected stickiness distribution (10 total unique users):
 *   Day 1: 6 users, Day 3: 3 users, Day 5: 1 user
 */
const stickyPowerUser = (): string => 'sticky-power-0'
const stickyRegularUser = (n: number): string => `sticky-regular-${n}`
const stickyCasualUser = (n: number): string => `sticky-casual-${n}`

export const stickinessPageviews = {
    events: [
        // Power user: active on 5 distinct days (daysAgo 0-4)
        ...createEvent({ event: '$pageview', user: stickyPowerUser, timestamp: daysAgo(0) }).repeat(1),
        ...createEvent({ event: '$pageview', user: stickyPowerUser, timestamp: daysAgo(1) }).repeat(1),
        ...createEvent({ event: '$pageview', user: stickyPowerUser, timestamp: daysAgo(2) }).repeat(1),
        ...createEvent({ event: '$pageview', user: stickyPowerUser, timestamp: daysAgo(3) }).repeat(1),
        ...createEvent({ event: '$pageview', user: stickyPowerUser, timestamp: daysAgo(4) }).repeat(1),
        // Regular users (3): active on 3 distinct days (daysAgo 0, 2, 4)
        ...createEvent({ event: '$pageview', user: stickyRegularUser, timestamp: daysAgo(0) }).repeat(3),
        ...createEvent({ event: '$pageview', user: stickyRegularUser, timestamp: daysAgo(2) }).repeat(3),
        ...createEvent({ event: '$pageview', user: stickyRegularUser, timestamp: daysAgo(4) }).repeat(3),
        // Casual users (6): active on 1 day only (daysAgo 1)
        ...createEvent({ event: '$pageview', user: stickyCasualUser, timestamp: daysAgo(1) }).repeat(6),
    ],
    expected: {
        day1: { users: 6, percent: 60 },
        day2: { users: 0, percent: 0 },
        day3: { users: 3, percent: 30 },
        day5: { users: 1, percent: 10 },
    },
}

/**
 * Stickiness custom events with browser breakdown.
 *
 * - 2 Chrome users (sticky-chrome-0..1): active on 3 days → Day 3
 * - 3 Firefox users (sticky-firefox-0..2): active on 1 day → Day 1
 *
 * Without breakdown (5 total):
 *   Day 1: 3 users, Day 3: 2 users
 * With breakdown by $browser:
 *   Chrome: Day 3 = 2 users
 *   Firefox: Day 1 = 3 users
 */
const stickyChromeUser = (n: number): string => `sticky-chrome-${n}`
const stickyFirefoxUser = (n: number): string => `sticky-firefox-${n}`

export const stickinessWithBreakdown = {
    eventName: 'sticky_test_event',
    events: [
        // Chrome users (2): active on 3 distinct days (daysAgo 0, 2, 4)
        ...createEvent({
            event: 'sticky_test_event',
            user: stickyChromeUser,
            timestamp: daysAgo(0),
            properties: { $browser: 'Chrome' },
        }).repeat(2),
        ...createEvent({
            event: 'sticky_test_event',
            user: stickyChromeUser,
            timestamp: daysAgo(2),
            properties: { $browser: 'Chrome' },
        }).repeat(2),
        ...createEvent({
            event: 'sticky_test_event',
            user: stickyChromeUser,
            timestamp: daysAgo(4),
            properties: { $browser: 'Chrome' },
        }).repeat(2),
        // Firefox users (3): active on 1 day only (daysAgo 1)
        ...createEvent({
            event: 'sticky_test_event',
            user: stickyFirefoxUser,
            timestamp: daysAgo(1),
            properties: { $browser: 'Firefox' },
        }).repeat(3),
    ],
    expected: {
        day1: { users: 3, percent: 60 },
        day2: { users: 0, percent: 0 },
        day3: { users: 2, percent: 40 },
    },
}
