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

import { createEvent, daysAgo } from './event-data'

const pvUser = (n: number): string => `pv-user-${n}`
const customUser = (n: number): string => `custom-user-${n}`
const retentionUser = (n: number): string => `retention-user-${n}`

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
        ...createEvent({ event: '$pageview', user: pvUser, timestamp: daysAgo(1) }).repeat(3),
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
 * Descending retention pattern: 10, 8, 6, 4, 3, 2, 1 over 7 days.
 * retention-user-N appears on days 6 through (6-N), giving a clean
 * retention curve where each cohort row shows decreasing return rates.
 */
export const retentionEvents = {
    eventName: 'retention_test_event',
    events: [
        ...createEvent({ event: 'retention_test_event', user: retentionUser, timestamp: daysAgo(6) }).repeat(10),
        ...createEvent({ event: 'retention_test_event', user: retentionUser, timestamp: daysAgo(5) }).repeat(8),
        ...createEvent({ event: 'retention_test_event', user: retentionUser, timestamp: daysAgo(4) }).repeat(6),
        ...createEvent({ event: 'retention_test_event', user: retentionUser, timestamp: daysAgo(3) }).repeat(4),
        ...createEvent({ event: 'retention_test_event', user: retentionUser, timestamp: daysAgo(2) }).repeat(3),
        ...createEvent({ event: 'retention_test_event', user: retentionUser, timestamp: daysAgo(1) }).repeat(2),
        ...createEvent({ event: 'retention_test_event', user: retentionUser, timestamp: daysAgo(0) }).repeat(1),
    ],
    expected: {
        initialCohortSize: 10,
        retentionPercentages: ['100.0%', '80.0%', '60.0%', '40.0%', '30.0%', '20.0%', '10.0%'],
    },
}
