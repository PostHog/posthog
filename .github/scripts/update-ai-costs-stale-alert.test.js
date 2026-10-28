const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const { findWaitingSince, findApprovedAt, isAlertDue, buildAlertText } = require('./update-ai-costs-stale-alert')

const HOUR_MS = 60 * 60 * 1000
const OPENED_AT = Date.parse('2026-10-20T10:05:00Z')
const at = (hours) => OPENED_AT + hours * HOUR_MS
const iso = (hours) => new Date(at(hours)).toISOString()

const costPr = ({ number, openedHours, closedHours = null, merged = false }) => ({
    number,
    html_url: `https://example.com/pull/${number}`,
    created_at: iso(openedHours),
    closed_at: closedHours === null ? null : iso(closedHours),
    merged_at: merged ? iso(closedHours) : null,
})

describe('update-ai-costs-stale-alert', () => {
    describe('isAlertDue', () => {
        const cases = [
            { name: 'sends the 2h alert in the hour it falls', fromHours: 1.5, untilHours: 2.5, due: true },
            { name: 'stays quiet between the 2h and 8h alerts', fromHours: 3.5, untilHours: 4.5, due: false },
            { name: 'sends the 8h alert after a dropped run', fromHours: 6.5, untilHours: 8.5, due: true },
            { name: 'does not repeat an alert on the window edge', fromHours: 2, untilHours: 3, due: false },
            { name: 'sends the first daily alert at 24h', fromHours: 23.5, untilHours: 24.5, due: true },
            { name: 'stays quiet between daily alerts', fromHours: 30.5, untilHours: 31.5, due: false },
            { name: 'sends a later daily alert at 72h', fromHours: 71.5, untilHours: 72.5, due: true },
            { name: 'catches up after a weekend without runs', fromHours: 30, untilHours: 92, due: true },
            { name: 'stays quiet before the PR opens', fromHours: -1, untilHours: 0, due: false },
        ]
        for (const { name, fromHours, untilHours, due } of cases) {
            it(name, () => {
                assert.equal(
                    isAlertDue({ stuckSince: OPENED_AT, lastCheckAt: at(fromHours), thisCheckAt: at(untilHours) }),
                    due
                )
            })
        }
    })

    describe('findWaitingSince', () => {
        const cases = [
            {
                name: 'starts at the only open PR',
                prs: [costPr({ number: 1, openedHours: 0 })],
                expected: { waitingSince: at(0), prCount: 1 },
            },
            {
                name: 'follows PRs the refresh replaced',
                prs: [
                    costPr({ number: 3, openedHours: 20 }),
                    costPr({ number: 2, openedHours: 10, closedHours: 19.99 }),
                    costPr({ number: 1, openedHours: 0, closedHours: 9.99 }),
                ],
                expected: { waitingSince: at(0), prCount: 3 },
            },
            {
                name: 'stops at a merged PR',
                prs: [
                    costPr({ number: 3, openedHours: 20 }),
                    costPr({ number: 2, openedHours: 10, closedHours: 19.99 }),
                    costPr({ number: 1, openedHours: 0, closedHours: 9.99, merged: true }),
                ],
                expected: { waitingSince: at(10), prCount: 2 },
            },
            {
                name: 'stops at a PR closed long before the next one opened',
                prs: [costPr({ number: 2, openedHours: 10 }), costPr({ number: 1, openedHours: 0, closedHours: 3 })],
                expected: { waitingSince: at(10), prCount: 1 },
            },
        ]
        for (const { name, prs, expected } of cases) {
            it(name, () => {
                assert.deepEqual(findWaitingSince(prs), expected)
            })
        }
    })

    describe('findApprovedAt', () => {
        const reviews = [
            { state: 'COMMENTED', submittedAt: iso(1) },
            { state: 'APPROVED', submittedAt: iso(3) },
            { state: 'APPROVED', submittedAt: iso(2) },
        ]
        const cases = [
            { name: 'uses the first approval of an approved PR', decision: 'APPROVED', expected: at(2) },
            { name: 'ignores approvals once review is required again', decision: 'REVIEW_REQUIRED', expected: null },
            { name: 'ignores approvals when changes are requested', decision: 'CHANGES_REQUESTED', expected: null },
        ]
        for (const { name, decision, expected } of cases) {
            it(name, () => {
                assert.equal(findApprovedAt(decision, reviews), expected)
            })
        }
    })

    describe('buildAlertText', () => {
        const pr = costPr({ number: 7, openedHours: 0 })
        const cases = [
            {
                name: 'tags only the support hero before 24h',
                nowHours: 23,
                approvedHours: null,
                prCount: 3,
                expected:
                    '<!subteam^HERO> LLM cost update <https://example.com/pull/7|#7> needs a review. New prices have waited 23h across 3 PRs.',
            },
            {
                name: 'adds AI observability from 24h',
                nowHours: 24,
                approvedHours: null,
                prCount: 1,
                expected:
                    '<!subteam^HERO> <!subteam^AIO> LLM cost update <https://example.com/pull/7|#7> needs a review. New prices have waited 24h.',
            },
            {
                name: 'points at the merge queue once approved',
                nowHours: 5,
                approvedHours: 2,
                prCount: 1,
                expected:
                    '<!subteam^HERO> LLM cost update <https://example.com/pull/7|#7> was approved 3h ago but has not merged. Check if the merge queue kicked it out. New prices have waited 5h.',
            },
        ]
        for (const { name, nowHours, approvedHours, prCount, expected } of cases) {
            it(name, () => {
                const text = buildAlertText({
                    pr,
                    waitingSince: OPENED_AT,
                    prCount,
                    approvedAt: approvedHours === null ? null : at(approvedHours),
                    now: at(nowHours),
                    supportHeroGroup: 'HERO',
                    aiObservabilityGroup: 'AIO',
                })
                assert.equal(text, expected)
            })
        }
    })
})
