import { dayjs } from 'lib/dayjs'

import type { TeamPublicType } from '~/types'

import type { Ticket } from '../../types'
import {
    DEFAULT_TICKET_GROUPS,
    TicketGroup,
    TicketGroupFilter,
    matchesFilter,
    teamTicketGroups,
    ticketGroupLabel,
    ticketGroupRank,
} from './ticketGroups'

const ticket = (overrides: Partial<Ticket> = {}): Ticket =>
    ({
        tags: [],
        channel_source: 'widget',
        status: 'open',
        created_at: '2026-07-15T12:00:00Z',
        ...overrides,
    }) as unknown as Ticket

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

describe('matchesFilter', () => {
    describe('ticket_tags any_of', () => {
        it('matches when the ticket has ANY of the tags (exact names)', () => {
            expect(matchesFilter(ticket({ tags: ['vip', 'billing'] }), tagsFilter('vip', 'urgent'))).toBe(true)
            expect(matchesFilter(ticket({ tags: ['billing'] }), tagsFilter('vip', 'urgent'))).toBe(false)
        })

        it('requires exact tag matches, not prefixes or substrings', () => {
            expect(matchesFilter(ticket({ tags: ['urgent_billing'] }), tagsFilter('urgent'))).toBe(false)
            expect(matchesFilter(ticket({ tags: ['vips'] }), tagsFilter('vip'))).toBe(false)
        })

        it('never matches a ticket without tags', () => {
            expect(matchesFilter(ticket({ tags: [] }), tagsFilter('vip'))).toBe(false)
            expect(matchesFilter(ticket({ tags: undefined }), tagsFilter('vip'))).toBe(false)
        })
    })

    describe('ticket_property in', () => {
        it.each([
            ['channel_source', ticket({ channel_source: 'email' }), ['email', 'slack'], true],
            ['channel_source', ticket({ channel_source: 'widget' }), ['email', 'slack'], false],
            ['status', ticket({ status: 'resolved' }), ['resolved'], true],
            ['status', ticket({ status: 'open' }), ['resolved'], false],
            ['priority', ticket({ priority: 'high' }), ['high', 'critical'], true],
            ['priority', ticket({ priority: 'low' }), ['high', 'critical'], false],
        ] as const)('matches %s membership', (key, subject, value, expected) => {
            expect(matchesFilter(subject, { type: 'ticket_property', key, operator: 'in', value: [...value] })).toBe(
                expected
            )
        })

        it('does not match when the property is unset', () => {
            expect(
                matchesFilter(ticket({ priority: undefined }), {
                    type: 'ticket_property',
                    key: 'priority',
                    operator: 'in',
                    value: ['high'],
                })
            ).toBe(false)
        })
    })

    describe('ticket_property email_from icontains', () => {
        const contains = (value: string): TicketGroupFilter => ({
            type: 'ticket_property',
            key: 'email_from',
            operator: 'icontains',
            value,
        })

        it('matches a case-insensitive substring', () => {
            expect(matchesFilter(ticket({ email_from: 'ceo@BigCorp.com' }), contains('@bigcorp.com'))).toBe(true)
            expect(matchesFilter(ticket({ email_from: 'ceo@bigcorp.com' }), contains('@OtherCorp.com'))).toBe(false)
        })

        it('never matches when email_from is null or undefined', () => {
            expect(matchesFilter(ticket({ email_from: null }), contains('@bigcorp.com'))).toBe(false)
            expect(matchesFilter(ticket({ email_from: undefined }), contains('@bigcorp.com'))).toBe(false)
        })
    })

    describe('ticket_property sla_due_at is_set / is_not_set', () => {
        it('is_set matches only when the SLA is present', () => {
            const filter: TicketGroupFilter = { type: 'ticket_property', key: 'sla_due_at', operator: 'is_set' }
            expect(matchesFilter(ticket({ sla_due_at: '2026-07-16T00:00:00Z' }), filter)).toBe(true)
            expect(matchesFilter(ticket({ sla_due_at: null }), filter)).toBe(false)
            expect(matchesFilter(ticket({ sla_due_at: undefined }), filter)).toBe(false)
        })

        it('is_not_set matches only when the SLA is absent', () => {
            const filter: TicketGroupFilter = { type: 'ticket_property', key: 'sla_due_at', operator: 'is_not_set' }
            expect(matchesFilter(ticket({ sla_due_at: null }), filter)).toBe(true)
            expect(matchesFilter(ticket({ sla_due_at: undefined }), filter)).toBe(true)
            expect(matchesFilter(ticket({ sla_due_at: '2026-07-16T00:00:00Z' }), filter)).toBe(false)
        })
    })

    describe('ticket_property created_at date_before / date_after', () => {
        // Jest pins TZ=UTC (frontend/jest.config.ts), so truncation assertions
        // are exact. Mid-day anchor so truncation-vs-rolling differences show.
        // This matrix must stay in lockstep with the backend's — see
        // TestResolveTicketGroupDateValue in
        // products/conversations/backend/api/tests/test_tickets.py.
        const now = dayjs('2026-07-20T12:00:00Z')
        const dateFilter = (operator: 'date_before' | 'date_after', value: string): TicketGroupFilter => ({
            type: 'ticket_property',
            key: 'created_at',
            operator,
            value,
        })

        it('resolves relative values against the injected now', () => {
            expect(
                matchesFilter(ticket({ created_at: '2026-07-10T12:00:00Z' }), dateFilter('date_before', '-3d'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-19T12:00:00Z' }), dateFilter('date_before', '-3d'), now)
            ).toBe(false)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-19T12:00:00Z' }), dateFilter('date_after', '-3d'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-10T12:00:00Z' }), dateFilter('date_after', '-3d'), now)
            ).toBe(false)
        })

        it('bare relative values are ROLLING windows, not midnight-anchored', () => {
            // Threshold is exactly now − 72h = 2026-07-17T12:00:00Z. A ticket
            // 71h old is inside; one 73h old is out — the old midnight-anchored
            // reading (00:00 on the 17th) would wrongly keep it in.
            expect(
                matchesFilter(ticket({ created_at: '2026-07-17T13:00:00Z' }), dateFilter('date_after', '-3d'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-17T11:00:00Z' }), dateFilter('date_after', '-3d'), now)
            ).toBe(false)
        })

        it('supports every unit: h, d, w, m, y', () => {
            // -12h → 2026-07-20T00:00Z; -2w → 2026-07-06T12:00Z;
            // -1m → 2026-06-20T12:00Z; -1y → 2025-07-20T12:00Z
            expect(
                matchesFilter(ticket({ created_at: '2026-07-20T06:00:00Z' }), dateFilter('date_after', '-12h'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-19T18:00:00Z' }), dateFilter('date_after', '-12h'), now)
            ).toBe(false)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-07T12:00:00Z' }), dateFilter('date_after', '-2w'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-05T12:00:00Z' }), dateFilter('date_after', '-2w'), now)
            ).toBe(false)
            expect(
                matchesFilter(ticket({ created_at: '2026-06-21T12:00:00Z' }), dateFilter('date_after', '-1m'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-06-19T12:00:00Z' }), dateFilter('date_after', '-1m'), now)
            ).toBe(false)
            expect(
                matchesFilter(ticket({ created_at: '2025-07-21T12:00:00Z' }), dateFilter('date_after', '-1y'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2025-07-19T12:00:00Z' }), dateFilter('date_after', '-1y'), now)
            ).toBe(false)
        })

        it('Start suffix subtracts then truncates to the start of the unit', () => {
            // -3dStart → 2026-07-17T00:00:00Z
            expect(
                matchesFilter(ticket({ created_at: '2026-07-17T06:00:00Z' }), dateFilter('date_after', '-3dStart'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-16T18:00:00Z' }), dateFilter('date_after', '-3dStart'), now)
            ).toBe(false)
            // -1mStart → 2026-06-01T00:00:00Z
            expect(
                matchesFilter(ticket({ created_at: '2026-06-15T00:00:00Z' }), dateFilter('date_after', '-1mStart'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-05-20T00:00:00Z' }), dateFilter('date_after', '-1mStart'), now)
            ).toBe(false)
        })

        it('End suffix subtracts then snaps to the end of the unit', () => {
            // -3dEnd → 2026-07-17T23:59:59.999Z
            expect(
                matchesFilter(ticket({ created_at: '2026-07-18T06:00:00Z' }), dateFilter('date_after', '-3dEnd'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2026-07-17T18:00:00Z' }), dateFilter('date_after', '-3dEnd'), now)
            ).toBe(false)
            // -1yEnd → 2025-12-31T23:59:59.999Z
            expect(
                matchesFilter(ticket({ created_at: '2026-01-15T00:00:00Z' }), dateFilter('date_after', '-1yEnd'), now)
            ).toBe(true)
            expect(
                matchesFilter(ticket({ created_at: '2025-06-01T00:00:00Z' }), dateFilter('date_after', '-1yEnd'), now)
            ).toBe(false)
        })

        it('accepts ISO datetime values', () => {
            const beforeIso = dateFilter('date_before', '2026-07-16T00:00:00Z')
            expect(matchesFilter(ticket({ created_at: '2026-07-15T12:00:00Z' }), beforeIso, now)).toBe(true)
            expect(matchesFilter(ticket({ created_at: '2026-07-17T12:00:00Z' }), beforeIso, now)).toBe(false)
            // Date-only, space-separated, and offset forms are all in the rule
            expect(
                matchesFilter(
                    ticket({ created_at: '2026-07-15T12:00:00Z' }),
                    dateFilter('date_before', '2026-07-16'),
                    now
                )
            ).toBe(true)
            expect(
                matchesFilter(
                    ticket({ created_at: '2026-07-15T12:00:00Z' }),
                    dateFilter('date_before', '2026-07-16 08:30'),
                    now
                )
            ).toBe(true)
            expect(
                matchesFilter(
                    ticket({ created_at: '2026-07-15T12:00:00Z' }),
                    dateFilter('date_before', '2026-07-16T08:30:00+02:00'),
                    now
                )
            ).toBe(true)
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
            '2026-1-1',
            '20260716',
            'garbage?!',
        ])('treats %s as unparseable — matches nothing under either operator', (value) => {
            // "3d"/"+3d" previously parsed as three days in the FUTURE, so
            // date_before matched every existing ticket; now they're
            // rejected outright. The write validator rejects all of these.
            const fresh = ticket({ created_at: '2026-07-19T12:00:00Z' })
            expect(matchesFilter(fresh, dateFilter('date_before', value), now)).toBe(false)
            expect(matchesFilter(fresh, dateFilter('date_after', value), now)).toBe(false)
        })
    })
})

describe('ticketGroupRank', () => {
    it('walks groups in order and takes the FIRST group whose filters all match', () => {
        // vip + urgent: Urgent (rank 1) precedes VIP (rank 2)
        expect(ticketGroupRank(ticket({ tags: ['vip', 'urgent'] }))).toBe(1)
        expect(ticketGroupRank(ticket({ tags: ['vip'] }))).toBe(2)
    })

    it('ranks unmatched tickets with the first group', () => {
        expect(ticketGroupRank(ticket({ tags: [] }))).toBe(0)
        expect(ticketGroupRank(ticket({ tags: ['team_replay', 'billing'] }))).toBe(0)
    })

    it('requires ALL of a group filters to match (AND)', () => {
        const groups: TicketGroup[] = [
            { label: 'Catch-all', filters: [] },
            {
                label: 'Urgent email',
                filters: [
                    tagsFilter('urgent'),
                    { type: 'ticket_property', key: 'channel_source', operator: 'in', value: ['email'] },
                ],
            },
        ]
        expect(ticketGroupRank(ticket({ tags: ['urgent'], channel_source: 'email' }), groups)).toBe(1)
        expect(ticketGroupRank(ticket({ tags: ['urgent'], channel_source: 'widget' }), groups)).toBe(0)
        expect(ticketGroupRank(ticket({ tags: [], channel_source: 'email' }), groups)).toBe(0)
    })

    it('treats a group with no filters as matching nothing', () => {
        const groups: TicketGroup[] = [
            { label: 'Placeholder', filters: [] },
            { label: 'VIPs', filters: [tagsFilter('vip')] },
        ]
        // vip skips the filter-less first group and lands on rank 1
        expect(ticketGroupRank(ticket({ tags: ['vip'] }), groups)).toBe(1)
        // unmatched falls back to rank 0 even though that group matches nothing
        expect(ticketGroupRank(ticket({ tags: ['other'] }), groups)).toBe(0)
    })

    it('threads the injected now into date filters', () => {
        const now = dayjs('2026-07-20T12:00:00Z')
        const groups: TicketGroup[] = [
            { label: 'Fresh', filters: [] },
            {
                label: 'Stale',
                filters: [{ type: 'ticket_property', key: 'created_at', operator: 'date_before', value: '-3d' }],
            },
        ]
        expect(ticketGroupRank(ticket({ created_at: '2026-07-10T12:00:00Z' }), groups, now)).toBe(1)
        expect(ticketGroupRank(ticket({ created_at: '2026-07-19T12:00:00Z' }), groups, now)).toBe(0)
    })
})

describe('ticketGroupLabel', () => {
    it.each([
        ['needs_triage', 'Triage'],
        ['urgent', 'Urgent'],
        ['vip', 'VIP'],
    ])('routes %s to %s by default', (tag, label) => {
        expect(ticketGroupLabel(ticket({ tags: [tag] }))).toBe(label)
    })

    it('falls back to the first group for unmatched tickets', () => {
        expect(ticketGroupLabel(ticket())).toBe('Triage')
    })

    it('labels against the provided groups instead of the default ladder', () => {
        const groups: TicketGroup[] = [
            { label: 'VIPs', filters: [tagsFilter('vip')] },
            { label: 'Everyone else', filters: [tagsFilter('plan_free')] },
        ]
        expect(ticketGroupLabel(ticket({ tags: ['plan_free'] }), groups)).toBe('Everyone else')
        expect(ticketGroupLabel(ticket({ tags: ['urgent'] }), groups)).toBe('VIPs')
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
                ],
            },
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
