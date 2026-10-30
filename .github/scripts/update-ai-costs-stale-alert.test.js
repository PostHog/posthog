const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const { findWaitingSince, isAlertDue, buildAlertText } = require('./update-ai-costs-stale-alert')

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
            { name: 'sends an alert when the PR opens', from: -0.5, until: 0.5, due: true },
            { name: 'stays quiet before the PR opens', from: -1.5, until: -0.5, due: false },
            { name: 'does not repeat an alert on the window edge', from: 0, until: 1, due: false },
            { name: 'stays quiet between the posted and 8h alerts', from: 3.5, until: 4.5, due: false },
            { name: 'sends the 8h alert after a dropped run', from: 6.5, until: 8.5, due: true },
            { name: 'sends the first daily alert at 24h', from: 23.5, until: 24.5, due: true },
            { name: 'stays quiet between daily alerts', from: 30.5, until: 31.5, due: false },
            { name: 'sends a later daily alert at 72h', from: 71.5, until: 72.5, due: true },
            { name: 'catches up after a weekend without runs', from: 30, until: 92, due: true },
        ]
        for (const { name, from, until, due } of cases) {
            it(name, () => {
                assert.equal(
                    isAlertDue({ waitingSince: OPENED_AT, lastCheckAt: at(from), thisCheckAt: at(until) }),
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

    describe('buildAlertText', () => {
        const pr = costPr({ number: 7, openedHours: 0 })
        const cases = [
            {
                name: 'announces a newly posted PR',
                nowHours: 0.25,
                prCount: 1,
                expected: '<!subteam^HERO> New LLM cost update <https://example.com/pull/7|#7> needs to merge.',
            },
            {
                name: 'tags only the support hero before 24h',
                nowHours: 23,
                prCount: 3,
                expected:
                    '<!subteam^HERO> LLM cost update <https://example.com/pull/7|#7> has not merged. New prices have waited 23h across 3 PRs.',
            },
            {
                name: 'adds AI observability from 24h',
                nowHours: 24,
                prCount: 1,
                expected:
                    '<!subteam^HERO> <!subteam^AIO> LLM cost update <https://example.com/pull/7|#7> has not merged. New prices have waited 24h.',
            },
        ]
        for (const { name, nowHours, prCount, expected } of cases) {
            it(name, () => {
                const text = buildAlertText({
                    pr,
                    waitingSince: OPENED_AT,
                    prCount,
                    now: at(nowHours),
                    supportHeroGroup: 'HERO',
                    aiObservabilityGroup: 'AIO',
                })
                assert.equal(text, expected)
            })
        }
    })
})
