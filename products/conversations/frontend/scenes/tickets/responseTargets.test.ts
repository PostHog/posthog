import type { TeamPublicType } from '~/types'

import {
    DEFAULT_RESPONSE_TARGET_GROUPS,
    responseTargetLabel,
    responseTargetRank,
    teamResponseTargetGroups,
} from './responseTargets'

describe('DEFAULT_RESPONSE_TARGET_GROUPS', () => {
    it('lists the example groups in priority order', () => {
        expect(DEFAULT_RESPONSE_TARGET_GROUPS.map((g) => g.label)).toEqual(['Triage', 'Urgent', 'VIP'])
    })

    it('never routes one tag to two groups', () => {
        const all = DEFAULT_RESPONSE_TARGET_GROUPS.flatMap((g) => g.tags)
        expect(new Set(all).size).toBe(all.length)
    })
})

describe('responseTargetLabel', () => {
    it.each([
        ['needs_triage', 'Triage'],
        ['urgent', 'Urgent'],
        ['vip', 'VIP'],
    ])('routes %s to %s by default', (tag, label) => {
        expect(responseTargetLabel([tag])).toBe(label)
    })

    it('takes the highest-priority group when several tags match', () => {
        expect(responseTargetLabel(['vip', 'urgent'])).toBe('Urgent')
    })

    it('falls back to the first group for untagged or unmatched tickets', () => {
        expect(responseTargetLabel([])).toBe('Triage')
        expect(responseTargetLabel(undefined)).toBe('Triage')
        expect(responseTargetLabel(['team_replay', 'billing'])).toBe('Triage')
    })

    it('requires exact tag matches, not prefixes or substrings', () => {
        expect(responseTargetLabel(['urgent_billing'])).toBe('Triage')
        expect(responseTargetLabel(['vips'])).toBe('Triage')
    })

    it('uses the provided groups instead of the default ladder', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: ['plan_free'] },
        ]
        expect(responseTargetLabel(['vip'], groups)).toBe('VIPs')
        expect(responseTargetLabel(['plan_free'], groups)).toBe('Everyone else')
        // urgent means nothing to this ladder → first group
        expect(responseTargetLabel(['urgent'], groups)).toBe('VIPs')
    })
})

describe('responseTargetRank', () => {
    it('ranks follow the group order, untagged with the first group', () => {
        expect(responseTargetRank(['needs_triage'])).toBe(0)
        expect(responseTargetRank([])).toBe(0)
        expect(responseTargetRank(['vip'])).toBe(DEFAULT_RESPONSE_TARGET_GROUPS.length - 1)
        expect(responseTargetRank(['urgent'])).toBeLessThan(responseTargetRank(['vip']))
    })

    it('ranks against provided groups', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: ['plan_free'] },
        ]
        expect(responseTargetRank(['plan_free'], groups)).toBe(1)
        expect(responseTargetRank(['vip', 'plan_free'], groups)).toBe(0)
    })
})

describe('teamResponseTargetGroups', () => {
    const teamWith = (settings: Record<string, any> | null): TeamPublicType =>
        ({ conversations_settings: settings }) as unknown as TeamPublicType

    it('returns the team-configured ladder when present and well-formed', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: [] },
        ]
        expect(teamResponseTargetGroups(teamWith({ response_target_groups: groups }))).toEqual(groups)
    })

    it.each([
        ['no team', undefined],
        ['no settings', null],
        ['key absent', {}],
        ['key null', { response_target_groups: null }],
        ['empty list', { response_target_groups: [] }],
        ['not a list', { response_target_groups: 'garbage' }],
        ['malformed items', { response_target_groups: [{ nope: true }] }],
        [
            'duplicate labels',
            {
                response_target_groups: [
                    { label: 'A', tags: ['x'] },
                    { label: 'A', tags: ['y'] },
                ],
            },
        ],
        [
            'a tag in two groups',
            {
                response_target_groups: [
                    { label: 'A', tags: ['vip'] },
                    { label: 'B', tags: ['vip', 'y'] },
                ],
            },
        ],
    ])('falls back to the default ladder with %s', (_name, settings) => {
        const team = settings === undefined ? null : teamWith(settings as Record<string, any> | null)
        expect(teamResponseTargetGroups(team)).toBe(DEFAULT_RESPONSE_TARGET_GROUPS)
    })
})
