import type { TeamPublicType } from '~/types'

import {
    DEFAULT_TICKET_GROUPS,
    TicketGroupFilter,
    isStructurallyUsableFilter,
    isValidTicketGroupDateValue,
    teamTicketGroups,
} from './ticketGroups'

const tagsFilter = (...tags: string[]): TicketGroupFilter => ({ type: 'ticket_tags', operator: 'any_of', value: tags })

describe('DEFAULT_TICKET_GROUPS', () => {
    it('mirrors the backend example groups exactly', () => {
        expect(DEFAULT_TICKET_GROUPS).toEqual([
            { label: 'Triage', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['needs_triage'] }] },
            { label: 'Urgent', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['urgent'] }] },
            { label: 'VIP', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['vip'] }] },
        ])
    })
})

describe('isValidTicketGroupDateValue', () => {
    // The grammar is shared with the backend serializer (which is what
    // actually resolves these) — this matrix must stay in lockstep with the
    // backend's write-validation tests in
    // products/conversations/backend/api/tests/test_tickets.py.
    it.each([
        '-3d',
        '-12h',
        '-2w',
        '-1m',
        '-1y',
        '-1000d',
        '-3dStart',
        '-3dEnd',
        '-1mStart',
        '-1yEnd',
        '2026-07-01',
        '2026-07-01T09:30',
        '2026-07-01T09:30:00',
        '2026-07-01T09:30:00.123',
        '2026-07-01 08:30',
        '2026-07-16T08:30:00Z',
        '2026-07-16T08:30:00+02:00',
    ])('accepts %s', (value) => {
        expect(isValidTicketGroupDateValue(value)).toBe(true)
    })

    it.each([
        '-3days',
        '3d ago',
        '3d',
        '+3d',
        '-3dstart',
        '-3DStart',
        '-0d',
        '-1001d',
        '-3',
        '2026-1-1',
        '20260716',
        'garbage?!',
        '',
    ])('rejects %s', (value) => {
        expect(isValidTicketGroupDateValue(value)).toBe(false)
    })
})

describe('isStructurallyUsableFilter', () => {
    it('accepts a sql filter with a non-empty expression', () => {
        expect(isStructurallyUsableFilter({ type: 'sql', expression: "priority = 'high'" })).toBe(true)
    })

    it.each([
        ['an empty expression', { type: 'sql', expression: '' }],
        ['a whitespace-only expression', { type: 'sql', expression: '   \n ' }],
        ['a non-string expression', { type: 'sql', expression: 5 }],
        ['a missing expression', { type: 'sql' }],
        ['an expression list', { type: 'sql', expression: ["priority = 'high'"] }],
    ])('rejects a sql filter with %s', (_name, filter) => {
        expect(isStructurallyUsableFilter(filter)).toBe(false)
    })

    it('still accepts the non-sql filter shapes', () => {
        expect(isStructurallyUsableFilter(tagsFilter('vip'))).toBe(true)
        expect(
            isStructurallyUsableFilter({ type: 'ticket_property', key: 'status', operator: 'in', value: ['open'] })
        ).toBe(true)
        expect(isStructurallyUsableFilter({ type: 'ticket_property', key: 'sla_due_at', operator: 'is_set' })).toBe(
            true
        )
    })

    it('accepts sla_state with an in operator, and rejects sla_due_at operators on it', () => {
        // sla_state (breached / at-risk / on-track) asks a different question from
        // sla_due_at is_set / is_not_set, so their operators aren't interchangeable.
        expect(
            isStructurallyUsableFilter({
                type: 'ticket_property',
                key: 'sla_state',
                operator: 'in',
                value: ['breached', 'at-risk'],
            })
        ).toBe(true)
        expect(isStructurallyUsableFilter({ type: 'ticket_property', key: 'sla_state', operator: 'is_set' })).toBe(
            false
        )
        expect(
            isStructurallyUsableFilter({ type: 'ticket_property', key: 'sla_state', operator: 'in', value: 'breached' })
        ).toBe(false)
    })
})

describe('teamTicketGroups', () => {
    const teamWith = (settings: Record<string, any> | null): TeamPublicType =>
        ({ conversations_settings: settings }) as unknown as TeamPublicType

    it('returns the team-configured groups when present and well-formed', () => {
        const groups = [
            { label: 'VIPs', filters: [tagsFilter('vip')] },
            { label: 'Everyone else', filters: [] },
        ]
        expect(teamTicketGroups(teamWith({ ticket_groups: groups }))).toEqual(groups)
    })

    it('accepts every filter shape in the vocabulary', () => {
        const groups = [
            {
                label: 'Kitchen sink',
                filters: [
                    tagsFilter('vip'),
                    { type: 'ticket_property', key: 'channel_source', operator: 'in', value: ['email'] },
                    { type: 'ticket_property', key: 'status', operator: 'in', value: ['open'] },
                    { type: 'ticket_property', key: 'priority', operator: 'in', value: ['high'] },
                    { type: 'ticket_property', key: 'email_from', operator: 'icontains', value: '@bigcorp.com' },
                    { type: 'ticket_property', key: 'sla_due_at', operator: 'is_set' },
                    { type: 'ticket_property', key: 'sla_due_at', operator: 'is_not_set' },
                    { type: 'ticket_property', key: 'created_at', operator: 'date_before', value: '-3d' },
                    { type: 'ticket_property', key: 'created_at', operator: 'date_after', value: '2026-01-01' },
                    { type: 'sql', expression: 'message_count > 5' },
                ],
            },
        ]
        expect(teamTicketGroups(teamWith({ ticket_groups: groups }))).toEqual(groups)
    })

    it('keeps a config whose only filter is a sql expression', () => {
        const groups = [
            { label: 'Chatty', filters: [{ type: 'sql', expression: "message_count > 5 AND priority = 'high'" }] },
            { label: 'Everyone else', filters: [] },
        ]
        expect(teamTicketGroups(teamWith({ ticket_groups: groups }))).toEqual(groups)
    })

    it('keeps groups whose filters overlap across groups (first match wins)', () => {
        const groups = [
            { label: 'A', filters: [tagsFilter('vip')] },
            { label: 'B', filters: [tagsFilter('vip', 'urgent')] },
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
        ['group not an object', { ticket_groups: ['garbage'] }],
        ['label missing', { ticket_groups: [{ filters: [] }] }],
        ['filters missing (old tags shape)', { ticket_groups: [{ label: 'A', tags: ['vip'] }] }],
        ['filters not a list', { ticket_groups: [{ label: 'A', filters: 'vip' }] }],
        ['filter not an object', { ticket_groups: [{ label: 'A', filters: ['vip'] }] }],
        ['unknown filter type', { ticket_groups: [{ label: 'A', filters: [{ type: 'person_property' }] }] }],
        [
            'ticket_tags with a string value',
            {
                ticket_groups: [{ label: 'A', filters: [{ type: 'ticket_tags', operator: 'any_of', value: 'vip' }] }],
            },
        ],
        [
            'ticket_tags with non-string entries',
            {
                ticket_groups: [{ label: 'A', filters: [{ type: 'ticket_tags', operator: 'any_of', value: [1] }] }],
            },
        ],
        [
            'ticket_tags with the wrong operator',
            {
                ticket_groups: [{ label: 'A', filters: [{ type: 'ticket_tags', operator: 'in', value: ['vip'] }] }],
            },
        ],
        [
            'a sql filter with an empty expression',
            { ticket_groups: [{ label: 'A', filters: [{ type: 'sql', expression: '  ' }] }] },
        ],
        [
            'a sql filter with a non-string expression',
            { ticket_groups: [{ label: 'A', filters: [{ type: 'sql', expression: 5 }] }] },
        ],
        [
            'unknown ticket property key',
            {
                ticket_groups: [
                    { label: 'A', filters: [{ type: 'ticket_property', key: 'nope', operator: 'in', value: ['x'] }] },
                ],
            },
        ],
        [
            'operator not valid for the key',
            {
                ticket_groups: [
                    {
                        label: 'A',
                        filters: [
                            { type: 'ticket_property', key: 'channel_source', operator: 'icontains', value: 'email' },
                        ],
                    },
                ],
            },
        ],
        [
            'in with a string value',
            {
                ticket_groups: [
                    {
                        label: 'A',
                        filters: [{ type: 'ticket_property', key: 'status', operator: 'in', value: 'open' }],
                    },
                ],
            },
        ],
        [
            'icontains with a list value',
            {
                ticket_groups: [
                    {
                        label: 'A',
                        filters: [{ type: 'ticket_property', key: 'email_from', operator: 'icontains', value: ['x'] }],
                    },
                ],
            },
        ],
        [
            'date filter with a non-string value',
            {
                ticket_groups: [
                    {
                        label: 'A',
                        filters: [{ type: 'ticket_property', key: 'created_at', operator: 'date_before', value: 3 }],
                    },
                ],
            },
        ],
        [
            'duplicate labels',
            {
                ticket_groups: [
                    { label: 'A', filters: [] },
                    { label: 'A', filters: [] },
                ],
            },
        ],
    ])('falls back to the default groups with %s', (_name, settings) => {
        const team = settings === undefined ? null : teamWith(settings as Record<string, any> | null)
        expect(teamTicketGroups(team)).toBe(DEFAULT_TICKET_GROUPS)
    })
})
