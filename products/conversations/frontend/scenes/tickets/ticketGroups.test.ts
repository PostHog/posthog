import type { TeamPublicType } from '~/types'

import { DEFAULT_TICKET_GROUPS, ticketGroupLabel, ticketGroupRank, teamTicketGroups } from './ticketGroups'

describe('DEFAULT_TICKET_GROUPS', () => {
    it('lists the example groups in priority order', () => {
        expect(DEFAULT_TICKET_GROUPS.map((g) => g.label)).toEqual(['Triage', 'Urgent', 'VIP'])
    })

    it('never routes one tag to two groups', () => {
        const all = DEFAULT_TICKET_GROUPS.flatMap((g) => g.tags)
        expect(new Set(all).size).toBe(all.length)
    })
})

describe('ticketGroupLabel', () => {
    it.each([
        ['needs_triage', 'Triage'],
        ['urgent', 'Urgent'],
        ['vip', 'VIP'],
    ])('routes %s to %s by default', (tag, label) => {
        expect(ticketGroupLabel([tag])).toBe(label)
    })

    it('takes the highest-priority group when several tags match', () => {
        expect(ticketGroupLabel(['vip', 'urgent'])).toBe('Urgent')
    })

    it('falls back to the first group for untagged or unmatched tickets', () => {
        expect(ticketGroupLabel([])).toBe('Triage')
        expect(ticketGroupLabel(undefined)).toBe('Triage')
        expect(ticketGroupLabel(['team_replay', 'billing'])).toBe('Triage')
    })

    it('requires exact tag matches, not prefixes or substrings', () => {
        expect(ticketGroupLabel(['urgent_billing'])).toBe('Triage')
        expect(ticketGroupLabel(['vips'])).toBe('Triage')
    })

    it('uses the provided groups instead of the default ladder', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: ['plan_free'] },
        ]
        expect(ticketGroupLabel(['vip'], groups)).toBe('VIPs')
        expect(ticketGroupLabel(['plan_free'], groups)).toBe('Everyone else')
        // urgent means nothing to this ladder → first group
        expect(ticketGroupLabel(['urgent'], groups)).toBe('VIPs')
    })
})

describe('ticketGroupRank', () => {
    it('ranks follow the group order, untagged with the first group', () => {
        expect(ticketGroupRank(['needs_triage'])).toBe(0)
        expect(ticketGroupRank([])).toBe(0)
        expect(ticketGroupRank(['vip'])).toBe(DEFAULT_TICKET_GROUPS.length - 1)
        expect(ticketGroupRank(['urgent'])).toBeLessThan(ticketGroupRank(['vip']))
    })

    it('ranks against provided groups', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: ['plan_free'] },
        ]
        expect(ticketGroupRank(['plan_free'], groups)).toBe(1)
        expect(ticketGroupRank(['vip', 'plan_free'], groups)).toBe(0)
    })
})

describe('teamTicketGroups', () => {
    const teamWith = (settings: Record<string, any> | null): TeamPublicType =>
        ({ conversations_settings: settings }) as unknown as TeamPublicType

    it('returns the team-configured ladder when present and well-formed', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: [] },
        ]
        expect(teamTicketGroups(teamWith({ ticket_groups: groups }))).toEqual(groups)
    })

    it.each([
        ['no team', undefined],
        ['no settings', null],
        ['key absent', {}],
        ['key null', { ticket_groups: null }],
        ['empty list', { ticket_groups: [] }],
        ['not a list', { ticket_groups: 'garbage' }],
        ['malformed items', { ticket_groups: [{ nope: true }] }],
        [
            'duplicate labels',
            {
                ticket_groups: [
                    { label: 'A', tags: ['x'] },
                    { label: 'A', tags: ['y'] },
                ],
            },
        ],
        [
            'a tag in two groups',
            {
                ticket_groups: [
                    { label: 'A', tags: ['vip'] },
                    { label: 'B', tags: ['vip', 'y'] },
                ],
            },
        ],
    ])('falls back to the default ladder with %s', (_name, settings) => {
        const team = settings === undefined ? null : teamWith(settings as Record<string, any> | null)
        expect(teamTicketGroups(team)).toBe(DEFAULT_TICKET_GROUPS)
    })
})
