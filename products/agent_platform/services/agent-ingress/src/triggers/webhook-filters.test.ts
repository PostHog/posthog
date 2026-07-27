import { describe, expect, it } from 'vitest'

import { payloadMatchesFilters } from './webhook-filters'

describe('payloadMatchesFilters', () => {
    const REVIEW_REQUESTED = {
        action: 'review_requested',
        pull_request: { number: 7, draft: false },
        requested_team: { slug: 'team-security' },
        installation: { id: 42 },
    }
    const TEAM_REVIEW_FILTERS = [
        { path: 'action', equals: 'review_requested' },
        { path: 'requested_team.slug', equals: 'team-security' },
    ]

    it('passes when every filter matches — the GitHub team-review-requested gate', () => {
        expect(payloadMatchesFilters(REVIEW_REQUESTED, TEAM_REVIEW_FILTERS)).toBe(true)
    })

    it.each<[string, unknown]>([
        ['a different action (synchronize noise)', { ...REVIEW_REQUESTED, action: 'synchronize' }],
        // Review requested from an individual carries requested_reviewer, not
        // requested_team — the path is absent and must not match.
        [
            'review requested from a user, not a team',
            { action: 'review_requested', requested_reviewer: { login: 'alice' } },
        ],
        ['a scalar where the path expects an object', { action: 'review_requested', requested_team: 'team-security' }],
        ['a null body', null],
    ])('rejects %s', (_label, body) => {
        expect(payloadMatchesFilters(body, TEAM_REVIEW_FILTERS)).toBe(false)
    })

    it('never matches a path routed through an array (documented objects-only limit)', () => {
        // Authors must address a scalar field, not one inside a list — a path
        // through an array resolves to no value, so the delivery is filtered.
        const body = { pull_request: { labels: [{ name: 'security' }] } }
        expect(payloadMatchesFilters(body, [{ path: 'pull_request.labels.0.name', equals: 'security' }])).toBe(false)
    })

    it('is AND semantics — one matching filter cannot carry a failing one', () => {
        const body = { action: 'review_requested', requested_team: { slug: 'team-platform' } }
        expect(payloadMatchesFilters(body, TEAM_REVIEW_FILTERS)).toBe(false)
    })

    it.each<[string, ReadonlyArray<{ path: string; equals: string | number | boolean }> | undefined]>([
        ['undefined filters', undefined],
        ['empty filters', []],
    ])('passes everything with %s — existing agents are unaffected', (_label, filters) => {
        expect(payloadMatchesFilters({ anything: true }, filters)).toBe(true)
    })

    it.each<[string, { path: string; equals: string | number | boolean }, boolean]>([
        ['number match', { path: 'installation.id', equals: 42 }, true],
        ['number mismatch', { path: 'installation.id', equals: 41 }, false],
        ['boolean match', { path: 'pull_request.draft', equals: false }, true],
        // Strict equality: the string '42' must not match the number 42.
        ['no cross-type coercion', { path: 'installation.id', equals: '42' }, false],
    ])('primitive equality: %s', (_label, filter, expected) => {
        expect(payloadMatchesFilters(REVIEW_REQUESTED, [filter])).toBe(expected)
    })

    it('resolves own properties only — prototype members are not payload data', () => {
        expect(payloadMatchesFilters({}, [{ path: 'constructor', equals: 'x' }])).toBe(false)
        expect(payloadMatchesFilters({ a: {} }, [{ path: 'a.toString', equals: 'x' }])).toBe(false)
    })
})
