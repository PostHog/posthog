// Ticket groups for the tickets list: ordered, filter-based groups. Group
// order IS the priority order (first group highest): a ticket takes the FIRST
// group whose filters ALL match (AND within a group, first-match-wins across
// groups), and tickets matching no group fall into the first group (they
// still need routing). A group with no filters matches nothing (a placeholder
// while configuring).
//
// Teams define their own groups in Settings → Support → Ticket groups
// (stored as conversations_settings.ticket_groups). Response-target ladders
// are one example use — the default below is only a starter example
// demonstrating the mechanic; every team's real groups are their own.
//
// Group MEMBERSHIP is computed SERVER-SIDE (products/conversations/backend/
// ticket_groups.py) and delivered on every serialized ticket as
// `ticket_group_rank`, the index of the ticket's group. The UI just looks that
// rank up in the group list to get a label.
//
// There is deliberately NO client-side evaluator here, and please don't add
// one back: a group filter can be a HogQL SQL expression (TicketSqlFilter),
// which only the server can compile and run. A browser evaluator would
// silently disagree with the server for every team using one. So this module
// holds only the config SHAPE, the config-reading fallback
// (teamTicketGroups), and the settings editor's pre-save checks.
//
// Tag matching is exact (no prefixes): a ticket tagged urgent_billing does
// NOT match a filter on the tag urgent.

import { dayjs } from 'lib/dayjs'

import type { TeamPublicType, TeamType } from '~/types'

export interface TicketTagsFilter {
    type: 'ticket_tags'
    operator: 'any_of'
    value: string[]
}

export interface TicketPropertyInFilter {
    type: 'ticket_property'
    /** `sla_state` is the same breached / at-risk / on-track vocabulary the ticket
     *  list's SLA filter uses (defined once in backend/sla.py). It asks a different
     *  question from `sla_due_at` is_set / is_not_set, which is whether the ticket
     *  has a deadline at all — all three states require one to exist. */
    key: 'channel_source' | 'status' | 'priority' | 'sla_state'
    operator: 'in'
    value: string[]
}

export interface TicketPropertyContainsFilter {
    type: 'ticket_property'
    key: 'email_from'
    operator: 'icontains'
    value: string
}

export interface TicketPropertySetFilter {
    type: 'ticket_property'
    key: 'sla_due_at'
    operator: 'is_set' | 'is_not_set'
}

export interface TicketPropertyDateFilter {
    type: 'ticket_property'
    key: 'created_at'
    operator: 'date_before' | 'date_after'
    /** A value in the shared date grammar (see the regexes below): a strict
     *  relative date ("-3d", "-1mStart") or an ISO datetime. Validated at
     *  write time on both sides; resolved server-side by the backend's
     *  _resolve_date_value. */
    value: string
}

export interface TicketSqlFilter {
    type: 'sql'
    /** A HogQL boolean expression over ticket columns, compiled to SQL
     *  server-side. Validated server-side (authoritative) — the browser can
     *  only length-check it. */
    expression: string
}

export type TicketGroupFilter =
    | TicketTagsFilter
    | TicketPropertyInFilter
    | TicketPropertyContainsFilter
    | TicketPropertySetFilter
    | TicketPropertyDateFilter
    | TicketSqlFilter

export interface TicketGroup {
    label: string
    filters: TicketGroupFilter[]
}

/** Longest SQL expression the editor will submit — the server enforces the
 *  same cap. */
export const MAX_TICKET_GROUP_SQL_LENGTH = 1000

export const DEFAULT_TICKET_GROUPS: TicketGroup[] = [
    // 0 (also the unmatched fallback)
    { label: 'Triage', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['needs_triage'] }] },
    { label: 'Urgent', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['urgent'] }] },
    { label: 'VIP', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['vip'] }] },
]

/** Valid operators per ticket_property key — mirrors the backend's
 *  _PROPERTY_OPERATORS. */
const PROPERTY_OPERATORS: Record<string, readonly string[]> = {
    channel_source: ['in'],
    status: ['in'],
    priority: ['in'],
    email_from: ['icontains'],
    sla_due_at: ['is_set', 'is_not_set'],
    sla_state: ['in'],
    created_at: ['date_before', 'date_after'],
}

// ## The shared created_at date grammar
//
// Both sides accept EXACTLY the same values (the serializer validates writes,
// ticketGroupsError pre-checks them in the editor):
//   - Relative: `-N<unit>` with unit in {h, d, w, m, y}, N an integer
//     1..1000, and an optional case-sensitive `Start`/`End` suffix — e.g.
//     "-3d", "-12h", "-1mStart", "-1yEnd". FULLMATCH only: no "+3d", "3d",
//     "-3days", "3d ago", "-3dstart".
//   - ISO datetime: zero-padded `YYYY-MM-DD`, optionally followed by a time
//     (`T` or space separator) and a `Z`/`±HH:MM` offset.
// Resolution happens server-side (_resolve_date_value, in the TEAM timezone):
// bare `-Nu` is a ROLLING window (now minus N units, time-of-day kept);
// `Start`/`End` subtract then snap to the start/end of the unit (weeks start
// on Sunday); naive ISO values take the team timezone.
//
// These two regexes are duplicated verbatim in ticket_groups.py.
const RELATIVE_DATE_REGEX = /^-([1-9][0-9]*)([hdwmy])(Start|End)?$/
const ISO_DATE_REGEX = /^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?$/
const MAX_RELATIVE_NUMBER = 1000

/** Whether a created_at filter value is in the shared date grammar — the
 *  pre-save check mirroring the serializer's rule. NOTE: impossible calendar
 *  dates ("2026-02-30") pass here (dayjs rolls them over) but the server
 *  rejects them; the server stays authoritative. */
export function isValidTicketGroupDateValue(value: string): boolean {
    const match = RELATIVE_DATE_REGEX.exec(value)
    if (match) {
        return parseInt(match[1], 10) <= MAX_RELATIVE_NUMBER
    }
    return ISO_DATE_REGEX.test(value) && dayjs(value).isValid()
}

function isStringList(value: unknown): value is string[] {
    return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

/** Enough shape to be a filter we can round-trip and send back — mirrors the
 *  backend's _is_structurally_usable_filter; the write validator is stricter
 *  (and is the only thing that can judge a SQL expression's validity). */
export function isStructurallyUsableFilter(filter: any): filter is TicketGroupFilter {
    if (!filter || typeof filter !== 'object') {
        return false
    }
    if (filter.type === 'ticket_tags') {
        return filter.operator === 'any_of' && isStringList(filter.value)
    }
    if (filter.type === 'sql') {
        return typeof filter.expression === 'string' && filter.expression.trim().length > 0
    }
    if (filter.type === 'ticket_property') {
        if (typeof filter.key !== 'string' || !(PROPERTY_OPERATORS[filter.key] ?? []).includes(filter.operator)) {
            return false
        }
        if (filter.operator === 'in') {
            return isStringList(filter.value)
        }
        if (filter.operator === 'is_set' || filter.operator === 'is_not_set') {
            return true // no value needed
        }
        // icontains / date_before / date_after — only the value type matters
        return typeof filter.value === 'string'
    }
    return false
}

/** The team's configured groups, or the default. The serializer validates
 *  writes, but the settings blob has other writers — treat anything malformed
 *  as unset. Returns the DEFAULT_TICKET_GROUPS reference itself when
 *  falling back, so memoization by identity keeps working. */
export function teamTicketGroups(team: TeamPublicType | TeamType | null): TicketGroup[] {
    const groups = team?.conversations_settings?.ticket_groups
    if (
        Array.isArray(groups) &&
        groups.length > 0 &&
        groups.every(
            (group: any) =>
                group &&
                typeof group === 'object' &&
                typeof group.label === 'string' &&
                Array.isArray(group.filters) &&
                group.filters.every(isStructurallyUsableFilter)
        ) &&
        // Duplicate labels would collide in the grouped view's per-label
        // headers — treat those as malformed too. (Filters overlapping across
        // groups are fine: first match wins, on both sides.)
        new Set(groups.map((group: any) => group.label)).size === groups.length
    ) {
        return groups as TicketGroup[]
    }
    return DEFAULT_TICKET_GROUPS
}
